// Browser file helpers for the tracer: read a plan image, download JSON.
import type { FloorImage } from "./store";

/** A plan image as an object URL with its pixel size. */
export function readImage(file: File): Promise<FloorImage> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      if (img.naturalWidth > 0 && img.naturalHeight > 0) {
        resolve({ url, w: img.naturalWidth, h: img.naturalHeight, name: file.name });
      } else {
        URL.revokeObjectURL(url);
        reject(new Error(`${file.name} has no pixel size; use a PNG or JPG`));
      }
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error(`${file.name} is not an image the browser can open (for a PDF, export the page as PNG first)`));
    };
    img.src = url;
  });
}

/** Save `data` as a pretty-printed JSON file. */
export function downloadJson(filename: string, data: unknown): void {
  const blob = new Blob([JSON.stringify(data, null, 2) + "\n"], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
