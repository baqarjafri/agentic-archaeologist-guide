/** A finger-tap ripple inside the phone frame, so a key press or a click on the laptop reads as a touch. */
export function showTapAt(x: number, y: number, frame: Element): void {
  const box = frame.getBoundingClientRect();
  const dot = document.createElement("span");
  dot.className = "tap-ripple";
  dot.style.left = `${x - box.left}px`;
  dot.style.top = `${y - box.top}px`;
  frame.appendChild(dot);
  setTimeout(() => dot.remove(), 600);
}

export function showTapOn(element: Element | null, frame: Element): void {
  if (!element) return;
  const r = element.getBoundingClientRect();
  showTapAt(r.left + r.width / 2, r.top + r.height / 2, frame);
}
