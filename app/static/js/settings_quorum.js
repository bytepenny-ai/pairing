/** Warns on the Models tab while the Matricxon cluster has no quorum: a download needs the cluster's pull
 * lease, so it would only fail. Silent for a standalone Matricxon or another engine (quorum "off"). */

const MODEL_QUORUM_REFRESH_MS = 15000;

async function refreshModelQuorumWarning() {
  const banner = document.getElementById("model-quorum-warning");
  if (!banner || document.hidden) return;
  try {
    const response = await fetch("/api/cluster/quorum");
    const body = response.ok ? await response.json() : { quorum: "off" };
    banner.classList.toggle("hidden", body.quorum !== "lost");
  } catch (_err) {
    /* unreachable: leave the banner as it was */
  }
}

// Only while its page is shown (page_views.js): no polling for a page nobody looks at.
let _modelQuorumTimer = null;
PageViews.whileShown(document.getElementById("model-quorum-warning"), (shown) => {
  clearInterval(_modelQuorumTimer);
  _modelQuorumTimer = shown ? setInterval(refreshModelQuorumWarning, MODEL_QUORUM_REFRESH_MS) : null;
  if (shown) refreshModelQuorumWarning();
});
