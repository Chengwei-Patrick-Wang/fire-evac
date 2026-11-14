// Browser file helpers for the tracer: read a plan image, shrink it for upload, download JSON.
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

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("the floor image could not be read again; upload it again"));
    img.src = url;
  });
}

function canvasBlob(canvas: HTMLCanvasElement, type: string, quality?: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("the browser could not encode the image"))), type, quality);
  });
}

/** A floor image as the AI first pass uploads it: at most maxSide px on its long side, on white
 * (a transparent plan would read as black), as PNG, or JPEG if the PNG is over 7 MB. */
export async function imageForUpload(url: string, maxSide = 1600): Promise<{ blob: Blob; w: number; h: number }> {
  const img = await loadImage(url);
  const k = Math.min(1, maxSide / Math.max(img.naturalWidth, img.naturalHeight));
  const w = Math.max(1, Math.round(img.naturalWidth * k));
  const h = Math.max(1, Math.round(img.naturalHeight * k));
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("the browser could not draw the image");
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, w, h);
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(img, 0, 0, w, h);
  let blob = await canvasBlob(canvas, "image/png");
  if (blob.size > 7 * 1024 * 1024) blob = await canvasBlob(canvas, "image/jpeg", 0.9);
  return { blob, w, h };
}
