export const clamp = (value: number, min: number, max: number): number =>
  Math.min(Math.max(value, min), max);

export const viewportWidth = (): number =>
  window.innerWidth || document.documentElement.clientWidth;

export const viewportHeight = (): number =>
  window.innerHeight || document.documentElement.clientHeight;
