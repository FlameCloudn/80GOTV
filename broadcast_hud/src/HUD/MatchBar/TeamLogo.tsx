import { Team } from 'csgogsi';
import * as I from '../../API/types';
import { apiUrl } from './../../API';
import { LogoCT, LogoT } from './../../assets/Icons';
import { useEffect, useState } from 'react';

const processedMatchLogoCache = new Map<string, string>();

const removeConnectedWhiteBackground = (image: HTMLImageElement) => {
    const canvas = document.createElement('canvas');
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const context = canvas.getContext('2d', { willReadFrequently: true });
    if (!context || !canvas.width || !canvas.height) return null;
    context.drawImage(image, 0, 0);
    const frame = context.getImageData(0, 0, canvas.width, canvas.height);
    const { data, width, height } = frame;
    const isBackground = (index: number) => {
        if (data[index + 3] < 16) return true;
        const red = data[index];
        const green = data[index + 1];
        const blue = data[index + 2];
        return red >= 220 && green >= 220 && blue >= 220
            && Math.max(red, green, blue) - Math.min(red, green, blue) <= 36;
    };
    const visited = new Uint8Array(width * height);
    const queue: number[] = [];
    const enqueue = (pixel: number) => {
        if (pixel < 0 || pixel >= width * height || visited[pixel]) return;
        const offset = pixel * 4;
        if (!isBackground(offset)) return;
        visited[pixel] = 1;
        queue.push(pixel);
    };
    for (let x = 0; x < width; x += 1) {
        enqueue(x);
        enqueue((height - 1) * width + x);
    }
    for (let y = 0; y < height; y += 1) {
        enqueue(y * width);
        enqueue(y * width + width - 1);
    }
    for (let cursor = 0; cursor < queue.length; cursor += 1) {
        const pixel = queue[cursor];
        const x = pixel % width;
        const y = Math.floor(pixel / width);
        data[pixel * 4 + 3] = 0;
        for (let yOffset = -1; yOffset <= 1; yOffset += 1) {
            for (let xOffset = -1; xOffset <= 1; xOffset += 1) {
                if (!xOffset && !yOffset) continue;
                const nextX = x + xOffset;
                const nextY = y + yOffset;
                if (nextX >= 0 && nextX < width && nextY >= 0 && nextY < height) {
                    enqueue(nextY * width + nextX);
                }
            }
        }
    }
    if (!queue.length) return null;
    context.putImageData(frame, 0, 0);
    return canvas.toDataURL('image/png');
};

const TeamLogo = ({team, height, width }: { team?: Team | I.Team | null, height?: number, width?: number}) => {
    const logo = team?.logo;
    const logoUrl = logo?.startsWith('/')
      ? `${apiUrl.replace(/\/$/, '')}${logo}`
      : logo;
    const source = logoUrl || (team && 'side' in team && team.side === "CT" ? LogoCT : LogoT);
    // Do not paint the raw uploaded logo first. That raw frame is the white
    // matte users see flashing before the transparent result is ready.
    const [displayLogo, setDisplayLogo] = useState(logoUrl ? '' : source);

    useEffect(() => {
      let cancelled = false;
      if (!logoUrl) {
        setDisplayLogo(source);
        return () => { cancelled = true; };
      }
      const cached = processedMatchLogoCache.get(logoUrl);
      if (cached) {
        setDisplayLogo(cached);
        return () => { cancelled = true; };
      }
      setDisplayLogo('');
      const image = new Image();
      image.crossOrigin = 'anonymous';
      image.onload = () => {
        if (cancelled) return;
        try {
          const processed = removeConnectedWhiteBackground(image);
          if (!cancelled) {
            // 处理不出透明图时回退显示原图，避免队标“消失”。
            const next = processed || logoUrl;
            processedMatchLogoCache.set(logoUrl, next);
            setDisplayLogo(next);
          }
        } catch {
          if (!cancelled) setDisplayLogo('');
        }
      };
      image.onerror = () => {
        if (!cancelled) setDisplayLogo('');
      };
      image.src = source;
      return () => { cancelled = true; };
    }, [logoUrl, source]);

    if(!team) return null;

    return (
      <div className={`logo`}>
          {displayLogo ? <img src={displayLogo} width={width} height={height} alt={'Team logo'} /> : null}
      </div>
    );

}

export default TeamLogo;
