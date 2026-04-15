// avatar.setState("speaking" | "thinking" | "listening" | "idle");

export class AnimeAvatar {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");

    this.worker = new Worker("avatar-worker.js");

    this.state = {
      sway: 0,
      headTilt: 0,
      hairSway: 0,
      pulse: 1,
      mouth: 0.05,
      eyeOpen: 1,
    };

    this.worker.onmessage = (e) => {
      if (e.data.type === "frame") {
        this.state = e.data;
        this.draw();
      }
    };
  }

  setState(state) {
    this.worker.postMessage({ type: "set-state", state });
  }

  draw() {
    const ctx = this.ctx;
    const { width, height } = this.canvas;

    ctx.clearRect(0, 0, width, height);

    ctx.save();

    // center
    ctx.translate(width / 2, height / 2);

    // breathing scale
    ctx.scale(this.state.pulse, this.state.pulse);

    // sway + tilt
    ctx.rotate((this.state.headTilt * Math.PI) / 180);
    ctx.translate(this.state.sway, 0);

    this.drawHair(ctx);
    this.drawFace(ctx);
    this.drawEyes(ctx);
    this.drawMouth(ctx);

    ctx.restore();
  }

  drawFace(ctx) {
    ctx.fillStyle = "#ffe0d6";

    ctx.beginPath();
    ctx.arc(0, 0, 80, 0, Math.PI * 2);
    ctx.fill();
  }

  drawHair(ctx) {
    ctx.fillStyle = "#2c1b47";

    ctx.beginPath();
    ctx.moveTo(-90, -40);
    ctx.quadraticCurveTo(0, -120, 90, -40);
    ctx.quadraticCurveTo(70, 60, 0, 90 + this.state.hairSway);
    ctx.quadraticCurveTo(-70, 60, -90, -40);
    ctx.fill();
  }

  drawEyes(ctx) {
    const eyeY = -10;
    const eyeOffsetX = 30;

    const open = this.state.eyeOpen;

    ctx.fillStyle = "#000";

    // left eye
    ctx.beginPath();
    ctx.ellipse(-eyeOffsetX, eyeY, 10, 10 * open, 0, 0, Math.PI * 2);
    ctx.fill();

    // right eye
    ctx.beginPath();
    ctx.ellipse(eyeOffsetX, eyeY, 10, 10 * open, 0, 0, Math.PI * 2);
    ctx.fill();
  }

  drawMouth(ctx) {
    const mouthY = 30;
    const openness = this.state.mouth * 30;

    ctx.strokeStyle = "#a33";
    ctx.lineWidth = 3;

    ctx.beginPath();
    ctx.ellipse(0, mouthY, 15, openness, 0, 0, Math.PI);
    ctx.stroke();
  }
}