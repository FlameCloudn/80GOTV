import { useEffect, useRef, useState } from "react";

type Props = {
  src: string;
  alt?: string;
  monochrome?: boolean;
  onError?: () => void;
};

const MAX_PROCESSING_DIMENSION = 256;
const processedLogoCache = new Map<string, string>();

const isNearWhite = (data: Uint8ClampedArray, offset: number) => {
  const alpha = data[offset + 3];
  if (alpha < 16) return true;
  const red = data[offset];
  const green = data[offset + 1];
  const blue = data[offset + 2];
  const spread = Math.max(red, green, blue) - Math.min(red, green, blue);
  // Team logos are often exported as an opaque white JPG/PNG. Use a little
  // tolerance for antialiased edges, but only remove pixels connected to the
  // outside so white details inside the logo remain untouched.
  return red >= 220 && green >= 220 && blue >= 220 && spread <= 36;
};

const removeEdgeWhite = (image: HTMLImageElement, monochrome: boolean): string | null => {
  const canvas = document.createElement("canvas");
  const renderScale = Math.min(1, MAX_PROCESSING_DIMENSION / Math.max(image.naturalWidth, image.naturalHeight));
  canvas.width = Math.max(1, Math.round(image.naturalWidth * renderScale));
  canvas.height = Math.max(1, Math.round(image.naturalHeight * renderScale));
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context || !canvas.width || !canvas.height) return null;

  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  const pixels = context.getImageData(0, 0, canvas.width, canvas.height);
  const { data, width, height } = pixels;
  const visited = new Uint8Array(width * height);
  const queue: number[] = [];

  const add = (pixel: number) => {
    if (pixel < 0 || pixel >= visited.length || visited[pixel] || !isNearWhite(data, pixel * 4)) return;
    visited[pixel] = 1;
    queue.push(pixel);
  };

  for (let x = 0; x < width; x += 1) {
    add(x);
    add((height - 1) * width + x);
  }
  for (let y = 0; y < height; y += 1) {
    add(y * width);
    add(y * width + width - 1);
  }

  for (let head = 0; head < queue.length; head += 1) {
    const pixel = queue[head];
    const x = pixel % width;
    const y = Math.floor(pixel / width);
    // Include diagonals so a white matte cannot remain in logo corners.
    for (let yOffset = -1; yOffset <= 1; yOffset += 1) {
      for (let xOffset = -1; xOffset <= 1; xOffset += 1) {
        if (!xOffset && !yOffset) continue;
        if (xOffset === -1 && x === 0) continue;
        if (xOffset === 1 && x + 1 >= width) continue;
        if (yOffset === -1 && y === 0) continue;
        if (yOffset === 1 && y + 1 >= height) continue;
        add(pixel + yOffset * width + xOffset);
      }
    }
  }

  visited.forEach((isBackground, pixel) => {
    if (isBackground) data[pixel * 4 + 3] = 0;
  });

  // Fade the one-pixel antialiased fringe around the removed matte. This
  // avoids a pale square/halo on dark halftime and result scenes without
  // touching isolated white parts of the actual logo.
  const touchesBackground = (pixel: number) => {
    const x = pixel % width;
    const y = Math.floor(pixel / width);
    for (let yOffset = -1; yOffset <= 1; yOffset += 1) {
      for (let xOffset = -1; xOffset <= 1; xOffset += 1) {
        if (!xOffset && !yOffset) continue;
        const nextX = x + xOffset;
        const nextY = y + yOffset;
        if (nextX >= 0 && nextX < width && nextY >= 0 && nextY < height
          && visited[nextY * width + nextX]) return true;
      }
    }
    return false;
  };
  for (let pixel = 0; pixel < visited.length; pixel += 1) {
    if (visited[pixel] || !touchesBackground(pixel)) continue;
    const offset = pixel * 4;
    if (data[offset + 3] < 16) continue;
    const red = data[offset];
    const green = data[offset + 1];
    const blue = data[offset + 2];
    const spread = Math.max(red, green, blue) - Math.min(red, green, blue);
    if (red < 180 || green < 180 || blue < 180 || spread > 48) continue;
    const brightness = (red + green + blue) / 3;
    const matte = Math.min(1, Math.max(0, (brightness - 180) / 75));
    data[offset + 3] = Math.round(data[offset + 3] * (1 - matte));
  }
  if (monochrome) {
    for (let pixel = 0; pixel < visited.length; pixel += 1) {
      const offset = pixel * 4;
      const alpha = data[offset + 3];
      const luminance = data[offset] * 0.2126 + data[offset + 1] * 0.7152 + data[offset + 2] * 0.0722;
      data[offset] = 255;
      data[offset + 1] = 255;
      data[offset + 2] = 255;
      data[offset + 3] = Math.round(alpha * (255 - luminance) / 255);
    }
  }
  context.putImageData(pixels, 0, 0);

  let minX = width;
  let minY = height;
  let maxX = -1;
  let maxY = -1;
  for (let pixel = 0; pixel < width * height; pixel += 1) {
    if (data[pixel * 4 + 3] < 16) continue;
    const x = pixel % width;
    const y = Math.floor(pixel / width);
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
  }
  if (maxX < minX || maxY < minY) return canvas.toDataURL("image/png");

  const normalized = document.createElement("canvas");
  const outputSize = Math.max(width, height);
  normalized.width = outputSize;
  normalized.height = outputSize;
  const normalizedContext = normalized.getContext("2d");
  if (!normalizedContext) return canvas.toDataURL("image/png");
  const sourceWidth = maxX - minX + 1;
  const sourceHeight = maxY - minY + 1;
  const targetSize = outputSize * 0.88;
  const scale = targetSize / Math.max(sourceWidth, sourceHeight);
  const targetWidth = sourceWidth * scale;
  const targetHeight = sourceHeight * scale;
  normalizedContext.drawImage(
    canvas,
    minX,
    minY,
    sourceWidth,
    sourceHeight,
    (outputSize - targetWidth) / 2,
    (outputSize - targetHeight) / 2,
    targetWidth,
    targetHeight,
  );
  return normalized.toDataURL("image/png");
};

const TeamLogoImage = ({ src, alt = "", monochrome = false, onError }: Props) => {
  const [displaySrc, setDisplaySrc] = useState("");
  const onErrorRef = useRef(onError);
  const sourceKeyRef = useRef<string | null>(null);

  // Some HUD parents refresh their data object every tick and create a new
  // callback each time. Keep that callback current without restarting logo
  // processing, otherwise the logo can visibly strobe between frames.
  useEffect(() => {
    onErrorRef.current = onError;
  }, [onError]);

  useEffect(() => {
    let cancelled = false;
    if (!src) {
      sourceKeyRef.current = null;
      setDisplaySrc("");
      return undefined;
    }

    const cacheKey = `${src}|${monochrome ? "mono" : "color"}`;
    if (sourceKeyRef.current !== cacheKey) {
      sourceKeyRef.current = cacheKey;
      setDisplaySrc("");
    }
    const cached = processedLogoCache.get(cacheKey);
    if (cached) {
      setDisplaySrc(cached);
      return undefined;
    }

    const image = new Image();
    image.crossOrigin = "anonymous";
    image.onload = () => {
      if (cancelled) return;
      try {
        const processed = removeEdgeWhite(image, monochrome);
        if (processed?.startsWith("data:image/")) {
          processedLogoCache.set(cacheKey, processed);
          setDisplaySrc(processed);
          return;
        }
        onErrorRef.current?.();
      } catch {
        onErrorRef.current?.();
      }
    };
    image.onerror = () => {
      if (!cancelled) onErrorRef.current?.();
    };
    image.src = src;

    return () => {
      cancelled = true;
    };
  }, [monochrome, src]);

  return displaySrc ? <img src={displaySrc} alt={alt} onError={onError} /> : null;
};

export default TeamLogoImage;
