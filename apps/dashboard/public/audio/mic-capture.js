// AudioWorklet: microphone (the context's rate, usually 48 kHz) -> 16 kHz mono PCM16 chunks of
// 20 ms, posted to the page, which sends them on the call's WebSocket.
const TARGET_RATE = 16000;
const CHUNK = 320; // 20 ms at 16 kHz

class MicCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / TARGET_RATE;
    this.pos = 0; // fractional read position into the incoming stream
    this.out = new Int16Array(CHUNK);
    this.filled = 0;
    this.prev = 0;
  }

  process(inputs) {
    const input = inputs[0] && inputs[0][0];
    if (!input) return true;
    // Linear-interpolation resampling; good enough for speech recognition.
    while (this.pos < input.length) {
      const i = Math.floor(this.pos);
      const frac = this.pos - i;
      const a = i === 0 ? this.prev : input[i - 1];
      const b = input[i];
      const s = Math.max(-1, Math.min(1, a + (b - a) * frac));
      this.out[this.filled++] = s < 0 ? s * 0x8000 : s * 0x7fff;
      if (this.filled === CHUNK) {
        this.port.postMessage(this.out.buffer.slice(0));
        this.filled = 0;
      }
      this.pos += this.ratio;
    }
    this.pos -= input.length;
    this.prev = input[input.length - 1];
    return true;
  }
}

registerProcessor("mic-capture", MicCapture);
