"""Embedding models from CATALOG.embedding_models cross-referenced with what the engine has pulled; the
analogue of model_catalog_service.ChatModelCatalogBuilder. Own file for the file-size rule and because
embedding_models is a disjoint list (CuratedCatalog) with no hidden-tags/per-user logic to share.
"""

import re

from sqlalchemy.ext.asyncio import AsyncSession

from app import hardware
from app.config import EMBEDDING_MODEL
from app.model_catalog import CATALOG
from app.schemas import EmbeddingCatalogEntry, EmbeddingModelCatalogResponse
from app.schemas.model_catalog import EngineModelSupport
from app.services.default_model_settings import DefaultModelSettings
from app.services.engine_support_checker import EngineSupportSet
from app.services.engines.registry import registry
from app.services.inference_client import list_models
from app.services.model_catalog_service import ChatModelCatalogBuilder


class EmbeddingModelCatalogService:
    """Open to any logged-in user, like GET /api/settings/rag-availability: install state isn't secret, only pulling
    is."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def build(self) -> EmbeddingModelCatalogResponse:
        installed_models = await list_models()
        installed_by_tag = {m["name"]: m for m in installed_models if "embedding" in m.get("capabilities", [])}
        capacity_gb = hardware.available_capacity_gb()
        support_set = await EngineSupportSet.load(installed_models)

        in_use = await DefaultModelSettings(self._db).embedding()
        entries = []
        for entry in CATALOG.embedding_models:
            installed_model = installed_by_tag.get(entry.tag)
            installed = installed_model is not None
            # Once installed, the engine's live report is the only source of architecture, with no fallback to the
            # curated guess (same as ChatModelCatalogBuilder._catalog_entry): the static value is a pre-install
            # estimate and must not outrank what is running.
            architecture = (
                ChatModelCatalogBuilder._clean_engine_reported(installed_model.get("details", {}).get("family"))
                if installed_model is not None
                else entry.architecture
            )
            engine_support = support_set.support_for(
                tag=entry.tag,
                architecture=architecture,
                quantizations=entry.quantizations,
                download_gb=entry.download_gb,
                min_ram_gb=entry.min_ram_gb,
            )
            entries.append(
                EmbeddingCatalogEntry(
                    family=entry.family,
                    vendor=entry.vendor,
                    tag=entry.tag,
                    parameter_size=entry.parameter_size,
                    context_length=entry.context_length,
                    embedding_dim=entry.embedding_dim,
                    download_gb=entry.download_gb,
                    min_ram_gb=entry.min_ram_gb,
                    engine_support=engine_support,
                    installed=installed,
                    hardware_ok=installed or capacity_gb >= entry.min_ram_gb,
                    unavailable_reason=entry.unavailable_reason,
                    in_use=entry.tag == in_use,
                )
            )

        # Installed from Hugging Face outside the catalog: listed too, so it can be chosen (it used to stay hidden).
        curated = {entry.tag for entry in CATALOG.embedding_models}
        for tag, model in installed_by_tag.items():
            if tag not in curated:
                entries.append(self._downloaded_entry(model, support_set, in_use))

        # The admin's choice if installed; otherwise the built-in default tag, so the "Default" badge points a
        # fresh install at something to pull.
        default_tag = in_use or EMBEDDING_MODEL

        return EmbeddingModelCatalogResponse(
            entries=entries, default_tag=default_tag, hardware=hardware.hardware_summary()
        )

    @staticmethod
    def _downloaded_entry(model: dict, support_set: EngineSupportSet, in_use: str | None) -> EmbeddingCatalogEntry:
        """An installed embedding model that isn't in the catalog, named from its tag
        ("hf.co/<vendor>/<repo>:<file>"). One the engine can't run (Matricxon's "tokenizer_unsupported") shows as not
        supported, with the reason, instead of failing on the first search."""
        tag = model["name"]
        details = model.get("details", {})
        repo = tag.split(":")[0].split("/")
        vendor = repo[-2] if len(repo) >= 2 else ""
        family = re.sub(r"(?i)[-.](gguf)$", "", repo[-1])
        size = details.get("parameter_size")
        download_gb = round(model["size"] / 1e9, 2) if model.get("size") else None
        min_ram_gb = float(model.get("estimated_ram_gb") or 0.0)
        support = support_set.support_for(
            tag=tag,
            architecture=ChatModelCatalogBuilder._clean_engine_reported(details.get("family")),
            quantizations=_quantizations_in(tag),
            download_gb=download_gb,
            min_ram_gb=min_ram_gb,
        )
        if "tokenizer_unsupported" in model.get("capabilities", []):
            engine = registry.active().name
            support[engine] = EngineModelSupport(
                supported=False, reason="Its tokenizer type isn't supported by this engine yet.", min_ram_gb=min_ram_gb
            )
        return EmbeddingCatalogEntry(
            family=family,
            vendor=vendor,
            tag=tag,
            parameter_size="" if size in (None, "unknown") else str(size),
            context_length=details.get("context_length"),
            download_gb=download_gb,
            min_ram_gb=min_ram_gb,
            engine_support=support,
            installed=True,
            hardware_ok=True,
            in_use=tag == in_use,
        )


_QUANTIZATION = re.compile(r"(?i)(?<![A-Z0-9])(IQ\d_[A-Z]+|Q\d_K(?:_[SML])?|Q\d_\d|BF16|F16|F32)(?![A-Z0-9])")


def _quantizations_in(tag: str) -> list[str] | None:
    """The tensor type of the quantization a tag's file name ends with ("…-Q4_K_M" is Q4_K: the _M only says how K
    types are mixed), as Matricxon names its supported types, for the engine support check."""
    found = _QUANTIZATION.findall(tag.split(":")[-1])
    return [re.sub(r"(_K)_[SML]$", r"\1", found[-1].upper())] if found else None
