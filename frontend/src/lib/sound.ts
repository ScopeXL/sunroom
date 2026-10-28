/**
 * The done moment's sound (UX §9): a soft 120 ms pop, synthesized, so there's no file to ship.
 * Off unless Settings → Display → Sounds is on, and only on the wall screen (a family's home is
 * loud enough, UX §11).
 */
let audio: AudioContext | null = null;

export function pop(): void {
  try {
    audio ??= new AudioContext();
    const now = audio.currentTime;
    const tone = audio.createOscillator();
    const level = audio.createGain();
    tone.type = "sine";
    tone.frequency.setValueAtTime(660, now);
    tone.frequency.exponentialRampToValueAtTime(990, now + 0.06);
    level.gain.setValueAtTime(0.0001, now);
    level.gain.exponentialRampToValueAtTime(0.18, now + 0.01);
    level.gain.exponentialRampToValueAtTime(0.0001, now + 0.12);
    tone.connect(level).connect(audio.destination);
    tone.start(now);
    tone.stop(now + 0.13);
  } catch {
    // No audio here (a test, or a browser that refuses): the moment is silent.
  }
}
