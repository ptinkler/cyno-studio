// Reload an <img> that failed to load, once, after `delay` ms. A cache-busting query makes the browser fetch it
// again instead of reusing the failure (a half-written file or a dropped connection usually fixes itself).
export function reloadImageLater(img, url, delay) {
  setTimeout(() => {
    img.src = `${url}${url.includes('?') ? '&' : '?'}retry=1`
  }, delay)
}
