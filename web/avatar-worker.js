let stageState = "idle";
let tick = 0;
let blinkFrame = 1;
let blinkCooldown = 16;

function nextBlink() {
  blinkCooldown -= 1;
  if (blinkCooldown <= 0) {
    blinkFrame = blinkFrame > 0 ? 0 : 1;
    if (blinkFrame === 1) {
      blinkCooldown = 18 + Math.floor(Math.random() * 16);
    } else {
      blinkCooldown = 1;
    }
  }
}

function nextFrame() {
  tick += 0.16;
  nextBlink();

  const sway = Math.sin(tick) * 6;
  const pulseBase = stageState === "thinking" ? 1.04 : stageState === "speaking" ? 1.06 : 1.02;
  const pulse = pulseBase + Math.sin(tick * 1.6) * 0.02;
  const mouth =
    stageState === "speaking"
      ? 0.45 + (Math.sin(tick * 4) + 1) * 0.18
      : stageState === "listening"
        ? 0.16
        : 0.04;

  postMessage({
    type: "frame",
    sway,
    pulse,
    blink: blinkFrame,
    mouth,
  });
}

onmessage = (event) => {
  const payload = event.data || {};
  if (payload.type === "set-state") {
    stageState = payload.state || "idle";
  }
};

setInterval(nextFrame, 80);