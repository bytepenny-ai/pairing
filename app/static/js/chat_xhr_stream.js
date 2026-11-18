/* A POST read as it arrives, over XMLHttpRequest rather than fetch: fetch has no upload progress event, which the
attachment progress bar (UploadProgress) needs. */
class XhrStream {
  /* Starts the request at once, so `xhr` can be aborted and watched right away. Returns { xhr, chunks }: `chunks` is
  an async generator of the response's new text, like a fetch body reader (responseText is already decoded). */
  static start(url, formData) {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    let seenLength = 0;
    let pending = null;
    const queued = [];
    let finished = false;
    let failure = null;

    const deliver = (value) => {
      if (pending) {
        pending.resolve(value);
        pending = null;
      } else {
        queued.push(value);
      }
    };
    const fail = (error) => {
      failure = error;
      finished = true;
      if (pending) pending.reject(failure);
    };
    xhr.addEventListener("progress", () => {
      const newText = xhr.responseText.slice(seenLength);
      seenLength = xhr.responseText.length;
      if (newText) deliver({ done: false, value: newText });
    });
    xhr.addEventListener("load", () => deliver({ done: true }));
    xhr.addEventListener("error", () => fail(new Error("Network error")));
    xhr.addEventListener("abort", () => fail(new DOMException("Aborted", "AbortError")));

    async function* chunks() {
      while (true) {
        if (queued.length) {
          const next = queued.shift();
          if (next.done) return;
          yield next.value;
          continue;
        }
        if (finished) {
          if (failure) throw failure;
          return;
        }
        const next = await new Promise((resolve, reject) => {
          pending = { resolve, reject };
        });
        if (next.done) return;
        yield next.value;
      }
    }

    xhr.send(formData);
    return { xhr, chunks: chunks() };
  }

  /* Resolves once the response status is known; rejects for anything but 200 with the server's `detail` (e.g. a 409
  "AI already replying") or a generic message, and the status on the error. */
  static whenAccepted(xhr) {
    return new Promise((resolve, reject) => {
      xhr.addEventListener("readystatechange", function onReady() {
        if (xhr.readyState < XMLHttpRequest.HEADERS_RECEIVED) return;
        xhr.removeEventListener("readystatechange", onReady);
        if (xhr.status === 200) {
          resolve();
          return;
        }
        xhr.addEventListener("loadend", () => {
          let message = `Request failed (${xhr.status})`;
          try {
            const errorBody = JSON.parse(xhr.responseText);
            if (errorBody.detail) message = errorBody.detail;
          } catch (_) {
            // Not JSON or no body: keep the generic message.
          }
          const error = new Error(message);
          error.status = xhr.status;
          reject(error);
        });
      });
    });
  }
}

/* A progress bar under the just-sent message's attachments, for the whole upload (one multipart body). */
class UploadProgress {
  // Over localhost a small file can finish before the next paint: the bar stays at least this long, to be seen.
  static MIN_VISIBLE_MS = 400;

  /* Shown at 0% at once (a small file may finish before any progress event), then follows the upload. */
  static follow(xhr, userWrapper) {
    UploadProgress.update(userWrapper, 0);
    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) UploadProgress.update(userWrapper, e.loaded / e.total);
    });
  }

  static update(userWrapper, fraction) {
    let bar = userWrapper.querySelector(".attachment-upload-progress");
    if (!bar) {
      bar = document.createElement("progress");
      bar.className = "attachment-upload-progress mt-1 block w-full h-1.5 accent-brand-500";
      bar.max = 1;
      bar.dataset.shownAt = String(performance.now());
      userWrapper.querySelector(".markdown-body").appendChild(bar);
    }
    bar.value = fraction;
  }

  /* Removes the bar when the upload ends (no-op without one). */
  static remove(userWrapper) {
    const bar = userWrapper.querySelector(".attachment-upload-progress");
    if (!bar) return;
    const elapsed = performance.now() - Number(bar.dataset.shownAt || 0);
    setTimeout(() => bar.remove(), Math.max(0, UploadProgress.MIN_VISIBLE_MS - elapsed));
  }
}
