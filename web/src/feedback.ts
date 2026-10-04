// Audible and haptic feedback, so operators don't have to look at the screen.

let ctx: AudioContext | null = null;

function tone(frequency: number, ms: number, delayMs = 0) {
  try {
    ctx ??= new AudioContext();
    const start = ctx.currentTime + delayMs / 1000;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = frequency;
    osc.type = "square";
    gain.gain.setValueAtTime(0.08, start);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + ms / 1000);
    osc.connect(gain).connect(ctx.destination);
    osc.start(start);
    osc.stop(start + ms / 1000);
  } catch {
    // audio not available; ignore
  }
}

export function feedback(kind: "ok" | "warn" | "error") {
  if (kind === "ok") {
    tone(1800, 90);
    navigator.vibrate?.(40);
  } else if (kind === "warn") {
    tone(900, 120);
    tone(900, 120, 180);
    navigator.vibrate?.([60, 60, 60]);
  } else {
    tone(300, 400);
    navigator.vibrate?.(300);
  }
}
