#!/usr/bin/env python3
"""
Local translation pipeline — Windows/Linux GPU, with GUI.

Modes:
  GUI  (default)   python local_pipeline.py
  CLI  (stdin)     python local_pipeline.py --no-gui --source-lang ja --target-lang vi
  Test (wav file)  python local_pipeline.py --test --test-file audio.wav

Install:
  pip install faster-whisper transformers torch accelerate sentencepiece
  pip install PySide6 sounddevice pyaudiowpatch scipy numpy
"""

import os

# ── Fix CUDA_PATH nếu bị thừa \bin ──────────────────────────
_cuda = os.environ.get("CUDA_PATH", "")
if _cuda.endswith("\\bin") or _cuda.endswith("/bin"):
    os.environ["CUDA_PATH"] = _cuda[:-4]   # bỏ \bin dư

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import torch
import sys
import json
import time
import wave
import tempfile
import threading
import argparse
import queue
from datetime import datetime
import numpy as np

# ─────────────────────────────────────────────────────────────────
# Language tables
# ─────────────────────────────────────────────────────────────────

LANG_NAMES: dict[str, str] = {
    "vi": "Vietnamese", "en": "English",    "ja": "Japanese",
    "ko": "Korean",     "zh": "Chinese",    "fr": "French",
    "de": "German",     "es": "Spanish",    "th": "Thai",
    "it": "Italian",    "pt": "Portuguese", "ru": "Russian",
    "ar": "Arabic",     "hi": "Hindi",      "nl": "Dutch",
    "pl": "Polish",     "tr": "Turkish",    "uk": "Ukrainian",
    "id": "Indonesian", "ms": "Malay",
}

WHISPER_LANG_MAP: dict[str, str | None] = {
    "auto": None,
    **{k: k for k in LANG_NAMES},
    "Japanese": "ja", "English": "en",  "Chinese": "zh",
    "Vietnamese": "vi", "Korean": "ko", "French": "fr",
    "German": "de", "Spanish": "es",    "Thai": "th",
}

LANG_DISPLAY: dict[str, str] = {v: k for k, v in LANG_NAMES.items()}
LANG_DISPLAY["Auto-detect"] = "auto"

WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v2", "large-v3", "large-v3-turbo"]

LLM_PRESETS = [
    "Qwen/Qwen2.5-1.5B-Instruct",
    "Qwen/Qwen2.5-3B-Instruct",
    "Qwen/Qwen2.5-7B-Instruct",
    "C:/Users/qt321/realtime_transcription/translategemma-4b-it-Q4_K_M_GGUF.gguf",
    # "azmnc/translategemma-4b-it-Q4_K_M_GGUF",   # ← GGUF, dùng llama-cpp-python
    # "google/gemma-2-2b-it",
    # "microsoft/Phi-3-mini-4k-instruct",
]

# ─────────────────────────────────────────────────────────────────
# CLI helpers
# ─────────────────────────────────────────────────────────────────

def log(msg: str):
    print(f"[pipeline] {msg}", file=sys.stderr, flush=True)

def emit_json(data: dict):
    print(json.dumps(data, ensure_ascii=False), flush=True)



# ─────────────────────────────────────────────────────────────────
# Stable transcript buffer — chống nhảy chữ Whisper real-time
# ─────────────────────────────────────────────────────────────────
class StableTranscriptBuffer:
    """
    Nhận liên tiếp các kết quả Whisper, chỉ expose phần text
    đã xuất hiện ổn định qua nhiều lần chạy.

    Cải tiến v2:
    - Fuzzy suffix matching: "five hours" ≈ "five hours a" → không reset
    - Soft confirm: suffix gần giống nhau tích lũy dần thay vì reset về 1
    - Bảo vệ confirmed tốt hơn: chỉ shrink sau 2 lần diverge liên tiếp
    """

    def __init__(self, confirm_runs: int = 2, diverge_tolerance: float = 0.35,
                 fuzzy_threshold: float = 0.6):
        self._confirmed        = ""
        self._candidate_suffix = ""
        self._candidate_count  = 0.0
        self._confirm_runs     = confirm_runs
        self._diverge_tol      = diverge_tolerance
        self._fuzzy_threshold  = fuzzy_threshold
        self._history: list[str] = []
        self._max_history      = 5
        self._diverge_streak   = 0

    def _common_prefix_words(self, a: str, b: str) -> int:
        wa, wb = a.lower().split(), b.lower().split()
        n = 0
        for x, y in zip(wa, wb):
            if x == y: n += 1
            else: break
        return n

    def _prefix_overlap(self, a: str, b: str) -> float:
        """Tỉ lệ prefix chung so với chuỗi ngắn hơn."""
        wa, wb = a.lower().split(), b.lower().split()
        if not wa or not wb: return 0.0
        common = 0
        for x, y in zip(wa, wb):
            if x == y: common += 1
            else: break
        return common / min(len(wa), len(wb))

    @property
    def confirmed(self) -> str:
        return self._confirmed

    def update(self, new_text: str) -> tuple[str, str]:
        """
        Trả về (confirmed, provisional).
        confirmed  : text ổn định, hiển thị sáng
        provisional: suffix chưa ổn định, hiển thị mờ
        """
        new_text = new_text.strip()
        if not new_text:
            return self._confirmed, ""

        self._history.append(new_text)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        confirmed_words = self._confirmed.split()
        new_words       = new_text.split()

        # ── 1. Kiểm tra confirmed còn hợp lệ trong new_text ──────────
        if confirmed_words:
            common = self._common_prefix_words(self._confirmed, new_text)
            overlap_ratio = common / len(confirmed_words)

            if overlap_ratio < (1.0 - self._diverge_tol):
                # Diverge — chỉ shrink sau 2 lần liên tiếp
                self._diverge_streak += 1
                if self._diverge_streak >= 2:
                    safe_words = new_words[:common]
                    self._confirmed        = " ".join(safe_words)
                    self._candidate_suffix = " ".join(new_words[common:])
                    self._candidate_count  = 1.0
                    self._diverge_streak   = 0
                else:
                    # Lần đầu diverge → giữ confirmed, chỉ cập nhật provisional
                    self._candidate_suffix = " ".join(new_words[len(confirmed_words):])
                return self._confirmed, self._candidate_suffix
            else:
                self._diverge_streak = 0

        # ── 2. Tính suffix mới (phần sau confirmed) ──────────────────
        suffix_words = new_words[len(confirmed_words):]
        new_suffix   = " ".join(suffix_words).strip()

        # ── 3. Fuzzy match suffix với candidate ──────────────────────
        if self._candidate_suffix:
            exact_match = (new_suffix == self._candidate_suffix)
            prefix_sim  = self._prefix_overlap(new_suffix, self._candidate_suffix)
            fuzzy_match = prefix_sim >= self._fuzzy_threshold

            if exact_match:
                self._candidate_count += 1.0        # exact → +1
            elif fuzzy_match:
                self._candidate_count += 0.6        # gần giống → +0.6
                self._candidate_suffix = new_suffix  # cập nhật suffix mới hơn
            else:
                # Khác → reset nhưng giữ chút đà
                self._candidate_suffix = new_suffix
                self._candidate_count  = max(0.3, self._candidate_count * 0.2)
        else:
            self._candidate_suffix = new_suffix
            self._candidate_count  = 1.0

        # ── 4. Promote nếu đủ điểm ───────────────────────────────────
        if self._candidate_count >= self._confirm_runs and new_suffix:
            self._confirmed        = new_text
            self._candidate_suffix = ""
            self._candidate_count  = 0.0

        return self._confirmed, self._candidate_suffix

    def reset(self):
        self._confirmed        = ""
        self._candidate_suffix = ""
        self._candidate_count  = 0.0
        self._diverge_streak   = 0
        self._history.clear()

# ─────────────────────────────────────────────────────────────────
# Core Pipeline
# ─────────────────────────────────────────────────────────────────

class LocalPipeline:
    def __init__(
        self,
        source_lang: str = "ja",
        target_lang: str = "vi",
        whisper_model: str = "large-v3-turbo",
        llm_model: str = "Qwen/Qwen2.5-1.5B-Instruct",
        device: str = "cuda",
        compute_type: str = "float16",
        chunk_seconds: int = 4,    # ↓ từ 7 → 4: xử lý sớm hơn 3 giây
        stride_seconds: int = 3,   # ↓ từ 5 → 3: overlap nhiều hơn, ít bỏ sót
        result_callback=None,
        status_callback=None,
    ):
        self.source_lang      = source_lang
        self.target_lang      = target_lang
        self.source_lang_name = LANG_NAMES.get(source_lang, source_lang.capitalize())
        self.target_lang_name = LANG_NAMES.get(target_lang, target_lang.capitalize())
        self.whisper_model_size = whisper_model
        self.llm_model_id     = llm_model
        self.device           = device
        self.compute_type     = compute_type
        self.chunk_seconds    = chunk_seconds
        self.stride_seconds   = stride_seconds
        self.sample_rate      = 16000
        self.bytes_per_sample = 2

        self.chunk_bytes  = chunk_seconds  * self.sample_rate * self.bytes_per_sample
        self.stride_bytes = stride_seconds * self.sample_rate * self.bytes_per_sample

        self.audio_buffer = bytearray()
        self.buf_lock = threading.Lock()
        self.running = True
        self._llm_lock = threading.Lock()  # ← THÊM DÒNG NÀY

        self.prev_text       = ""
        self.context_history: list[tuple[str, str]] = []
        self.max_context     = 5

        self._result_cb = result_callback or (lambda *a: None)
        self._status_cb = status_callback or log

        self.whisper        = None
        self.llm_model_obj  = None
        self.llm_tokenizer  = None
        self._models_ready  = threading.Event()

        # Async translation queue: Whisper puts (text, lang, timing) here,
        # a separate thread picks it up and calls LLM without blocking audio
        self._trans_q: queue.Queue = queue.Queue(maxsize=2)
        self._trans_thread: threading.Thread | None = None

    def _status(self, msg: str):
        self._status_cb(msg)

    def load_models(self):
        try:
            self._load_whisper()
            self._load_llm()
            self._status("Warming up LLM…")
            self._translate("Hello, warm-up.")
            self._models_ready.set()
            # Start async translation thread after models are ready
            self._trans_thread = threading.Thread(
                target=self._trans_worker, daemon=True)
            self._trans_thread.start()
            self._status("✓ Ready")
        except Exception as e:
            self._status(f"Load error: {e}")
            raise

    def _load_whisper(self):
        from faster_whisper import WhisperModel
        # ── Tối ưu compute_type để chia sẻ GPU với GGUF ──────────────
        # float16:      ~3.0GB VRAM + GGUF 2.5GB = 5.5GB → OOM trên RTX 3060 6GB
        # int8_float16: ~1.5GB VRAM + GGUF 2.5GB = 4.0GB → an toàn, tốc độ gần bằng
        if self._is_gguf() and self.device == "cuda":
            whisper_compute = "int8_float16"
        else:
            whisper_compute = self.compute_type

        self._status(f"Loading Whisper [{self.whisper_model_size}] on {self.device} ({whisper_compute})…")
        t = time.time()
        self.whisper = WhisperModel(
            self.whisper_model_size,
            device       = self.device,
            compute_type = whisper_compute,
        )
        self._status(f"Whisper loaded ({time.time()-t:.1f}s) [{self.device}/{whisper_compute}]")

    def _is_gguf(self) -> bool:
        """Check if the configured LLM is a GGUF model (uses llama-cpp backend)."""
        return "GGUF" in self.llm_model_id.upper() or self.llm_model_id.endswith(".gguf")

    def _load_llm(self):
        self._status(f"Loading LLM [{self.llm_model_id}]…")
        t = time.time()

        if self._is_gguf():
            # ── GGUF backend: llama-cpp-python ──────────────────────
            # Ẩn AMD GPU, chỉ để NVIDIA (CUDA luôn đánh số NVIDIA là 0)
            os.environ["CUDA_VISIBLE_DEVICES"] = "0"

            try:
                from llama_cpp import Llama
            except ImportError:
                raise ImportError(
                    "llama-cpp-python not installed.\n"
                    "Install with CUDA support:\n"
                    "  pip install llama-cpp-python==0.3.4 "
                    "--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124 "
                    "--only-binary=:all:"
                )

            # ── Kiểm tra GPU khả dụng trước khi thử load ──────────────
            import torch as _torch
            _use_gpu = _torch.cuda.is_available() and self.device == "cuda"
            _n_gpu   = -1 if _use_gpu else 0

            try:
                if os.path.isfile(self.llm_model_id):
                    self.llm_model_obj = Llama(
                        model_path    = self.llm_model_id,
                        n_gpu_layers  = _n_gpu,
                        n_ctx         = 2048,
                        main_gpu      = 0,      # ← chỉ định GPU 0, tránh xung đột context
                        verbose       = False,
                    )
                else:
                    self.llm_model_obj = Llama.from_pretrained(
                        repo_id      = self.llm_model_id,
                        filename     = "*Q4_K_M*.gguf",
                        n_gpu_layers = _n_gpu,
                        n_ctx        = 2048,
                        main_gpu     = 0,
                        verbose      = False,
                    )
                if _use_gpu:
                    log(f"[GGUF] Loaded on GPU ✓")
            except Exception as gpu_err:
                import traceback
                log(f"[GGUF] GPU load failed: {gpu_err}")
                log(f"[GGUF] Detail: {traceback.format_exc()}")
                self._status("⚠ GGUF GPU failed, loading on CPU…")

                # Fallback CPU
                if os.path.isfile(self.llm_model_id):
                    self.llm_model_obj = Llama(
                        model_path   = self.llm_model_id,
                        n_gpu_layers = 0,
                        n_ctx        = 2048,
                        verbose      = False,
                    )
                else:
                    self.llm_model_obj = Llama.from_pretrained(
                        repo_id      = self.llm_model_id,
                        filename     = "*Q4_K_M*.gguf",
                        n_gpu_layers = 0,
                        n_ctx        = 2048,
                        verbose      = False,
                    )
            self.llm_tokenizer = None  # llama-cpp handles tokenization internally
        else:
            # ── HuggingFace transformers backend (default) ───────────
            import torch
            from transformers import AutoTokenizer, AutoModelForCausalLM
            # Nếu là đường dẫn folder chứa model Transformers local, hàm này vẫn tự đọc được
            self.llm_tokenizer = AutoTokenizer.from_pretrained(
                self.llm_model_id, trust_remote_code=True
            )
            dtype = torch.float16 if self.device == "cuda" else torch.float32
            self.llm_model_obj = AutoModelForCausalLM.from_pretrained(
                self.llm_model_id,
                dtype=dtype,
                device_map=self.device,
                trust_remote_code=True,
            ).eval()

        self._status(f"LLM loaded ({time.time() - t:.1f}s)")

    def _trans_worker(self):
        """
        Dedicated LLM translation thread.
        Picks (text, lang, t_asr, t_start) from _trans_q,
        translates with 1 retry on empty result, fires result_callback.
        """
        while True:
            item = self._trans_q.get()
            if item is None:
                break
            text, lang, t_asr, t_start = item
            t1 = time.time()

            translated = self._translate(text)

            # Retry once on empty/garbage output
            if not translated.strip():
                log(f"[trans_worker] Empty result, retrying: {text[:60]}")
                time.sleep(0.2)
                translated = self._translate(text)

            t_llm  = time.time() - t1
            total  = time.time() - t_start
            self._result_cb(text, translated, lang, {
                "asr":       round(t_asr, 2),
                "translate": round(t_llm, 2),
                "total":     round(total, 2),
            })

    def _save_wav(self, pcm_bytes: bytes) -> str:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        with wave.open(tmp.name, "w") as wf:
            wf.setnchannels(1); wf.setsampwidth(2)
            wf.setframerate(self.sample_rate); wf.writeframes(pcm_bytes)
        return tmp.name

    def _transcribe(self, wav_path: str) -> tuple[str, str]:
        """Tier 3 — chính xác, dùng khi commit cuối."""
        lang = WHISPER_LANG_MAP.get(self.source_lang)
        segments, info = self.whisper.transcribe(
            wav_path, language=lang, task="transcribe",
            beam_size=5, vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            condition_on_previous_text=False,  # ← THÊM: tránh hallucination
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        return text, (info.language or self.source_lang)

    def _transcribe_fast(self, wav_path: str, initial_prompt: str = "") -> tuple[str, str]:
        """Tier 1 — nhanh cho live preview, dùng initial_prompt để anchor."""
        lang = WHISPER_LANG_MAP.get(self.source_lang)
        kwargs = dict(
            language  = lang,
            task      = "transcribe",
            beam_size = 1,
            vad_filter= True,
            vad_parameters = {"min_silence_duration_ms": 300},
            condition_on_previous_text = False,
            temperature = 0.0,
        )
        # Truyền confirmed text làm hint → Whisper ít hallucinate hơn
        if initial_prompt and len(initial_prompt.split()) >= 3:
            kwargs["initial_prompt"] = initial_prompt
        segments, info = self.whisper.transcribe(wav_path, **kwargs)
        text = " ".join(s.text.strip() for s in segments).strip()
        return text, (info.language or self.source_lang)

    def _transcribe_with_segments(self, wav_path: str) -> tuple[list[dict], str]:
        """
        Returns list of {text, start, end, no_speech_prob} + detected language.
        Caller decides how to accumulate/commit segments.
        """
        lang = WHISPER_LANG_MAP.get(self.source_lang)
        segments_gen, info = self.whisper.transcribe(
            wav_path, language=lang, task="transcribe",
            beam_size=5, vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        result = []
        for s in segments_gen:
            text = s.text.strip()
            if not text:
                continue
            result.append({
                "text":           text,
                "start":          s.start,
                "end":            s.end,
                "no_speech_prob": getattr(s, "no_speech_prob", 0.0),
            })
        return result, (info.language or self.source_lang)

    def _build_prompt(self, text: str) -> str:
        src, tgt = self.source_lang_name, self.target_lang_name

        # Context ngắn — chỉ lượt cuối
        ctx = ""
        if self.context_history:
            prev_orig, prev_trans = self.context_history[-1]
            ctx = f"Previous: '{prev_orig}' = '{prev_trans}'\n"

        messages = [
            {"role": "system", "content": (
                f"You are a real-time {src}→{tgt} translator.\n"
                f"Output ONLY the {tgt} translation. No labels, no explanations.\n"
                f"Keep names and technical terms unchanged.\n"
                f"1-2 sentences max. If input is partial, translate what's there."
            )},
            {"role": "user", "content": f"{ctx}Translate to {tgt}: {text}"},
        ]
        if hasattr(self.llm_tokenizer, "apply_chat_template"):
            return self.llm_tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True)
        prompt = ""
        for m in messages:
            prompt += f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n"
        return prompt + "<|im_start|>assistant\n"

    def _translate(self, text: str, max_tokens: int = 200) -> str:
        if not text.strip() or self.llm_model_obj is None:
            return ""
        import re

        if self._is_gguf():
            result = self._translate_gguf(text, max_tokens=max_tokens)
        else:
            result = self._translate_hf(text, max_tokens=max_tokens)

        # ── Post-processing (shared) ──────────────────────────────
        for tok in ["<|im_end|>", "<|endoftext|>", "<end_of_turn>", "</s>", "<eos>"]:
            result = result.split(tok)[0]
        result = re.sub(r"<[^>]+>", "", result)
        result = re.sub(
            rf"^({re.escape(self.target_lang_name)}:\s*|{self.target_lang.upper()}:\s*|→\s*|Translate:\s*)",
            "", result, flags=re.IGNORECASE)
        lines  = [l.strip() for l in result.splitlines() if l.strip()]
        result = lines[0] if lines else ""
        result = re.sub(r"\s+", " ", result).strip()

        # Strip CJK if target is not CJK
        if self.target_lang not in ("zh", "ja", "ko"):
            result = re.sub(r'[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]+', '', result)
            result = re.sub(r'[\u3000-\u303f]+', '', result)
            result = re.sub(r'[\uff00-\uffef]+', '', result)
            result = re.sub(r"\s+", " ", result).strip()

        # Garbage validation
        if result and self.target_lang not in ("zh", "ja", "ko", "ar", "th"):
            import unicodedata
            valid_chars = sum(
                1 for c in result
                if unicodedata.category(c).startswith(('L', 'N', 'Z', 'P'))
                and ord(c) < 0x3000
            )
            total_chars = len(result.replace(" ", ""))
            if total_chars > 0 and valid_chars / total_chars < 0.5:
                log(f"[translate] Rejected garbage output: {repr(result)}")
                result = ""

        # Overlap dedup
        if result and self.context_history:
            wn, wp = result.split(), self.context_history[-1][1].split()
            if len(wn) >= 3 and len(wp) >= 3:
                overlap = 0
                for i in range(3, min(len(wn), len(wp)) + 1):
                    if " ".join(wp[-i:]).lower() == " ".join(wn[:i]).lower():
                        overlap = i
                if overlap >= 3:
                    result = " ".join(wn[overlap:]).strip()

        if result:
            self.context_history.append((text, result))
            if len(self.context_history) > self.max_context * 2:
                self.context_history = self.context_history[-self.max_context:]
        return result

    # def _translate_gguf(self, text: str, max_tokens: int = 200) -> str:
    #     """Translate using llama-cpp-python (GGUF backend)."""
    #     src_code = self.source_lang  # "en", "ja", "vi"...
    #     tgt_code = self.target_lang
    #     tgt = self.target_lang_name
    #
    #     # Context ngắn gọn
    #     ctx = ""
    #     if self.context_history:
    #         prev_orig, prev_trans = self.context_history[-1]
    #         ctx = f"Previous: '{prev_orig}' = '{prev_trans}'\n"
    #
    #     # translategemma dùng format [sprt] đặc biệt trong chat template
    #     # format: "src_code[sprt]tgt_code[sprt]text"
    #     user_content = f"{src_code}[sprt]{tgt_code}[sprt]{text}"
    #
    #     messages = [
    #         {"role": "user", "content": user_content},
    #         {"role": "assistant", "content": ""},  # ← trigger generation
    #     ]
    #     try:
    #         with self._llm_lock:
    #             response = self.llm_model_obj.create_chat_completion(
    #                 messages=messages,
    #                 max_tokens=max_tokens,
    #                 temperature=0.0,
    #             )
    #         return response["choices"][0]["message"]["content"].strip()
    #     except Exception as e:
    #         log(f"[gguf translate] {e}")
    #         return ""

    def _translate_gguf(self, text: str, max_tokens: int = 400) -> str:
        src_code = self.source_lang
        tgt_code = self.target_lang

        messages = []

        # 1. Đưa lịch sử câu trước vào làm Context (Ngữ cảnh)
        # Chỉ lấy 1 hoặc 2 câu gần nhất để model không bị quá tải và dịch nhanh hơn
        if self.context_history:
            for prev_orig, prev_trans in self.context_history[-1:]:
                # Giả lập lại lượt hỏi của User
                messages.append({
                    "role": "user",
                    "content": f"{src_code}[sprt]{tgt_code}[sprt]{prev_orig}"
                })
                # Giả lập lại câu trả lời của AI
                messages.append({
                    "role": "assistant",
                    "content": prev_trans
                })

        # 2. Đưa câu hiện tại cần dịch vào
        messages.append({
            "role": "user",
            "content": f"{src_code}[sprt]{tgt_code}[sprt]{text.lower()}"
        })

        try:
            with self._llm_lock:
                resp = self.llm_model_obj.create_chat_completion(
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=0.0
                )
            return resp["choices"][0]["message"]["content"].strip()
        except Exception as e:
            log(f"[gguf] {e}")
            return ""

    def _translate_hf(self, text: str, max_tokens: int = 200) -> str:
        """Translate using HuggingFace transformers backend."""
        import torch
        prompt = self._build_prompt(text)
        inputs = self.llm_tokenizer(prompt, return_tensors="pt").to(self.device)
        with self._llm_lock:
            with torch.no_grad():
                out = self.llm_model_obj.generate(
                    **inputs,
                    max_new_tokens=max_tokens,
                    do_sample=False,
                    repetition_penalty=1.1,
                    eos_token_id=self.llm_tokenizer.eos_token_id,
                    pad_token_id=self.llm_tokenizer.eos_token_id,
                )
        new_toks = out[0][inputs["input_ids"].shape[-1]:]
        return self.llm_tokenizer.decode(new_toks, skip_special_tokens=True).strip()

    def _dedup(self, text: str) -> str:
        if not self.prev_text or not text:
            return text
        best, limit = 0, min(len(self.prev_text), len(text), 120)
        for n in range(3, limit + 1):
            if self.prev_text[-n:] == text[:n]:
                best = n
        if best >= 3:
            r = text[best:].strip()
            return r if r else text
        return text

    def process_chunk(self, pcm_bytes: bytes):
        samples = np.frombuffer(pcm_bytes, dtype=np.int16)
        rms = np.sqrt(np.mean(samples.astype(np.float32) ** 2))
        if rms < 80:
            return
        wav_path = self._save_wav(pcm_bytes)
        try:
            t_start = time.time()

            # ── Step 1: Whisper (fast, ~0.3-1s) ──
            text, lang = self._transcribe(wav_path)
            t_asr = time.time() - t_start

            if not text or text == self.prev_text:
                return
            new_text = self._dedup(text)
            if not new_text or len(new_text) < 2:
                self.prev_text = text
                return

            self.prev_text = text

            # ── Step 2: Push to async LLM queue (non-blocking) ──
            # If queue is full (LLM is busy), drop the oldest item first
            if self._trans_q.full():
                try:
                    self._trans_q.get_nowait()
                except queue.Empty:
                    pass
            self._trans_q.put_nowait((new_text, lang, t_asr, t_start))

        finally:
            try: os.unlink(wav_path)
            except OSError: pass

    def run_stdin(self):
        def reader():
            try:
                while self.running:
                    data = sys.stdin.buffer.read(4096)
                    if not data: break
                    with self.buf_lock:
                        self.audio_buffer.extend(data)
            finally:
                self.running = False
        threading.Thread(target=reader, daemon=True).start()
        pos = 0
        while self.running:
            time.sleep(0.5)
            with self.buf_lock:
                blen = len(self.audio_buffer)
            if blen - pos >= self.chunk_bytes:
                with self.buf_lock:
                    chunk = bytes(self.audio_buffer[pos: pos + self.chunk_bytes])
                self.process_chunk(chunk)
                pos += self.stride_bytes
        with self.buf_lock:
            rem = bytes(self.audio_buffer[pos:])
        if len(rem) > self.sample_rate * 2:
            self.process_chunk(rem)


# ═════════════════════════════════════════════════════════════════
# GUI
# ═════════════════════════════════════════════════════════════════

def run_gui(args):
    from PySide6.QtCore import (Qt, QTimer, Signal, QRectF, QThread,
                                 QPoint, QSize)
    from PySide6.QtGui import (QPainter, QColor, QTextCursor, QPalette,
                                QLinearGradient, QPainterPath, QCursor)
    from PySide6.QtWidgets import (
        QApplication, QWidget, QVBoxLayout, QHBoxLayout,
        QTextEdit, QPushButton, QComboBox, QLabel, QFrame,
        QSizeGrip, QStackedWidget,
    )
    import sounddevice as sd

    try:
        import pyaudiowpatch as pyaudio
        HAS_WASAPI = True
    except ImportError:
        HAS_WASAPI = False

    try:
        from scipy.signal import resample as scipy_resample
        HAS_SCIPY = True
    except ImportError:
        HAS_SCIPY = False

    # ── Palette ───────────────────────────────
    BG       = "#0d1117"
    BG2      = "#161b22"
    BG_PANEL = "#10161e"
    BORDER   = "#30363d"
    TEXT     = "#e6edf3"
    MUTED    = "#8b949e"
    BLUE     = "#58a6ff"
    GREEN    = "#38d9a9"
    RED_BG   = "#7f1d1d"
    RED_BR   = "#dc2626"
    GRN_BG   = "#14532d"
    GRN_BR   = "#16a34a"
    ACCENT   = "#1f6feb"

    COMBO_SM = (f"QComboBox{{background:{BG2};color:#c9d1d9;"
                f"border:1px solid {BORDER};border-radius:4px;"
                f"padding:2px 6px;font-size:11px;min-width:80px;}}"
                f"QComboBox::drop-down{{border:none;width:14px;}}"
                f"QComboBox QAbstractItemView{{background:{BG2};color:#c9d1d9;"
                f"border:1px solid {BORDER};selection-background-color:{ACCENT};}}")

    BTN_SM = ("QPushButton{{background:{bg};color:{fg};border:1px solid {br};"
              "border-radius:4px;padding:3px 10px;font-size:11px;font-weight:600;}}"
              "QPushButton:hover{{background:{hv};}}"
              "QPushButton:disabled{{color:#484f58;background:#161b22;border-color:#21262d;}}")

    LBL_SM = f"QLabel{{color:{MUTED};font-size:10px;}}"

    # ── Tiny waveform ─────────────────────────
    class MiniWaveform(QWidget):
        def __init__(self):
            super().__init__()
            self.setFixedHeight(28)
            self.waves  = [0.0] * 40
            self.target = [0.0] * 40
            self.active = False
            t = QTimer(self); t.timeout.connect(self._tick); t.start(33)

        def start(self): self.active = True
        def stop(self):  self.active = False; self.target = [0.0] * 40

        def push(self, data):
            if not self.active or len(data) == 0: return
            norm = np.abs(data) / (np.max(np.abs(data)) + 1e-10)
            n, chunk = 40, max(1, len(norm) // 40)
            self.target = [float(norm[i:i+chunk].mean()) * 1.5
                           for i in range(0, len(norm), chunk)][:n]
            while len(self.target) < n: self.target.append(0.0)

        def _tick(self):
            t = time.time()
            for i in range(40):
                tgt = self.target[i] * (1 + np.sin(t*6+i)*0.1) if self.active else 0.0
                self.waves[i] += (tgt - self.waves[i]) * 0.25
            self.update()

        def paintEvent(self, _):
            p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
            try:
                w, h, cy = self.width(), self.height(), self.height() / 2
                bw = w / (40 * 1.6); mh = h * 0.85
                for i, amp in enumerate(self.waves):
                    bh = max(1.5, mh * amp)
                    alpha = 220 if self.active else 60
                    p.setBrush(QColor(56, 217, 169, alpha))
                    p.setPen(Qt.NoPen)
                    p.drawRoundedRect(
                        QRectF(w*i/40 + bw*0.3, cy-bh/2, bw, bh),
                        bw/2, bw/2)
            finally: p.end()

    # ── Subtitle panel (video-style) ─────────
    # Flowing paragraph, no timestamps, live cursor ■
    class SubtitlePanel(QWidget):
        """
        Displays text as a flowing paragraph like the video:
        - History sentences slightly dimmed
        - Latest live text bright with blinking ■ cursor
        - No timestamps
        """
        MAX_CHARS = 800   # keep last N chars of history

        def __init__(self, label: str, accent: str, dim_history: bool = True):
            super().__init__()
            self._accent      = accent
            self._dim_history = dim_history
            self._history: list[str] = []   # committed sentences
            self._live: str = ""            # current live text (updating)
            self._cursor_on  = True
            self._lang_label = label

            lay = QVBoxLayout(self)
            lay.setContentsMargins(8, 6, 8, 6)
            lay.setSpacing(4)

            # Speaker-style label (like "Speaker 1:" in video)
            self._spk_lbl = QLabel(label)
            self._spk_lbl.setStyleSheet(
                f"QLabel{{color:{accent};font-size:11px;font-weight:700;}}")
            lay.addWidget(self._spk_lbl)

            self.edit = QTextEdit()
            self.edit.setReadOnly(True)
            self.edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.edit.setStyleSheet(
                f"QTextEdit{{background:transparent;color:{TEXT};"
                f"border:none;padding:0px 2px;"
                f"font-size:14px;line-height:1.6;}}")
            lay.addWidget(self.edit, stretch=1)

            # Blinking cursor timer
            self._cur_timer = QTimer()
            self._cur_timer.timeout.connect(self._blink)
            self._cur_timer.start(600)
            self._draft: str = ""  # speculative translation (dimmer)

        def _blink(self):
            # Blink cho cả 2 path: live cũ và stable mới
            has_live = bool(self._live) or bool(
                getattr(self, '_confirmed_live', '') or
                getattr(self, '_provisional_live', '')
            )
            if has_live:
                self._cursor_on = not self._cursor_on
                self._render()

        def set_live(self, text: str, lang: str = ""):
            """Update the live (in-progress) part."""
            self._live = text
            self._cursor_on = True
            self._render()

        def set_live_stable(self, confirmed: str, provisional: str):
            """Live text với 2 màu: confirmed sáng, provisional mờ hơn."""
            self._confirmed_live = confirmed
            self._provisional_live = provisional
            self._cursor_on = True
            self._render()

        def set_draft(self, text: str):
            """
            Show speculative/incremental translation in draft style (dim italic).
            Replaced by final translation when commit() is called.
            """
            self._draft = text
            self._render()

        def commit(self, text: str):
            """Sentence complete — move to history, clear live + draft."""
            if text.strip():
                self._history.append(text.strip())
                while sum(len(s) for s in self._history) > self.MAX_CHARS and len(self._history) > 1:
                    self._history.pop(0)
            self._live  = ""
            self._draft = ""
            self._confirmed_live = ""   # ← Xóa chữ khi chốt câu
            self._provisional_live = "" # ← Xóa chữ khi chốt câu
            self._render()

        def append(self, text: str):
            """Directly add a completed sentence — also clears draft."""
            self._draft = ""
            if text.strip():
                self._history.append(text.strip())
                while sum(len(s) for s in self._history) > self.MAX_CHARS and len(self._history) > 1:
                    self._history.pop(0)
            self._render()

        def clear(self):
            self._history.clear()
            self._live  = ""
            self._draft = ""
            self._confirmed_live = ""   # ← Xóa chữ
            self._provisional_live = "" # ← Xóa chữ
            self.edit.clear()

        @staticmethod
        def _esc(t):
            return t.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

        def _render(self):
            parts = []

            # 1. Committed history
            for i, sent in enumerate(self._history):
                age = len(self._history) - 1 - i
                if self._dim_history:
                    if age == 0:   color = "#8b949e"
                    elif age == 1: color = "#4b5263"
                    else:          color = "#30363d"
                else:
                    color = TEXT
                parts.append(
                    f"<p style='margin:0 0 3px 0;padding:0;color:{color}'>"
                    f"{self._esc(sent)}</p>")

            # 2. Draft translation (Tiếng Việt nháp)
            if self._draft:
                parts.append(
                    f"<p style='margin:0 0 2px 0;padding:0;"
                    f"color:{self._accent};opacity:0.7;"
                    f"font-style:italic;'>"
                    f"{self._esc(self._draft)}"
                    f"<span style='opacity:0.5'> ✦</span></p>")

            # 3. Live ASR text — Bổ sung logic 2 màu (Stable/Provisional)
            if hasattr(self, '_confirmed_live') and (self._confirmed_live or self._provisional_live):
                cursor = "▌" if self._cursor_on else "\u00a0"
                confirmed_part   = self._esc(self._confirmed_live) if self._confirmed_live else ""
                provisional_part = self._esc(self._provisional_live) if self._provisional_live else ""
                # Khi confirmed rỗng → provisional là text duy nhất → dùng màu sáng TEXT
                # Khi confirmed có chữ → provisional là phần chưa ổn định → dùng MUTED
                provisional_color = MUTED if confirmed_part else TEXT
                space = ' ' if confirmed_part and provisional_part else ''
                parts.append(
                    f"<p style='margin:0;padding:0;'>"
                    f"<span style='color:{TEXT}'>{confirmed_part}</span>"
                    f"<span style='color:{provisional_color}'>{space}{provisional_part}</span>"
                    f"<span style='color:{self._accent}'>{cursor}</span>"
                    f"</p>"
                )
            elif self._live:
                cursor = "▌" if self._cursor_on else "\u00a0"
                parts.append(
                    f"<p style='margin:0;padding:0;color:{TEXT}'>"
                    f"{self._esc(self._live)}"
                    f"<span style='color:{self._accent}'>{cursor}</span></p>")

            self.edit.setHtml("".join(parts))
            c = self.edit.textCursor()
            c.movePosition(QTextCursor.MoveOperation.End)
            self.edit.setTextCursor(c)

    # Keep CompactPanel as alias for backward compatibility
    CompactPanel = SubtitlePanel


    # ── Settings panel (hidden by default) ────
    # ── Settings panel (hidden by default) ────
    class SettingsPanel(QWidget):
        def __init__(self, init_args, has_wasapi):
            super().__init__()
            self.setStyleSheet(
                f"QWidget{{background:{BG_PANEL};"
                f"border-top:1px solid {BORDER};}}")

            lay = QHBoxLayout(self)
            lay.setContentsMargins(8, 6, 8, 6)
            lay.setSpacing(8)

            def lbl(t):
                l = QLabel(t);
                l.setStyleSheet(LBL_SM);
                return l

            # --- Whisper Combo ---
            lay.addWidget(lbl("Whisper:"))
            self.w_model = QComboBox()
            self.w_model.addItems(WHISPER_MODELS)
            self.w_model.setCurrentText(init_args.whisper_model)
            self.w_model.setStyleSheet(COMBO_SM)
            lay.addWidget(self.w_model)

            # --- LLM Combo + Nút Browse ---
            lay.addWidget(lbl("LLM:"))
            llm_box = QHBoxLayout()
            llm_box.setSpacing(2)

            self.llm_combo = QComboBox()
            self.llm_combo.setEditable(True)
            self.llm_combo.addItems(LLM_PRESETS)
            self.llm_combo.setCurrentText(init_args.llm_model)
            self.llm_combo.setMinimumWidth(180)
            self.llm_combo.setStyleSheet(COMBO_SM)
            llm_box.addWidget(self.llm_combo)

            # Nút 📁 Browse cho phép chọn file GGUF
            self.btn_browse = QPushButton("📁")
            self.btn_browse.setFixedSize(26, 26)
            self.btn_browse.setStyleSheet(
                f"QPushButton{{background:transparent; color:{TEXT}; border:none; font-size:14px;}}"
                f"QPushButton:hover{{background:{BG2}; border-radius:4px;}}"
            )
            self.btn_browse.setToolTip("Select the .gguf file saved on your computer.")
            self.btn_browse.clicked.connect(self._browse_llm)
            llm_box.addWidget(self.btn_browse)

            lay.addLayout(llm_box)

            # --- Device & Source Combo ---
            lay.addWidget(lbl("Device:"))
            self.dev_combo = QComboBox()
            self.dev_combo.addItems(["cuda", "cpu"])
            self.dev_combo.setCurrentText(init_args.device)
            self.dev_combo.setStyleSheet(COMBO_SM)
            lay.addWidget(self.dev_combo)

            lay.addWidget(lbl("Source:"))
            self.src_combo = QComboBox()
            sources = ["Micro"]
            if has_wasapi: sources.append("WASAPI Loopback")
            self.src_combo.addItems(sources)
            self.src_combo.setStyleSheet(COMBO_SM)
            lay.addWidget(self.src_combo)

            lay.addStretch()

            # --- Reload Button ---
            self.reload_btn = QPushButton("⟳ Reload")
            self.reload_btn.setStyleSheet(BTN_SM.format(
                bg=BG2, fg=MUTED, br=BORDER, hv="#21262d"))
            lay.addWidget(self.reload_btn)

        def _browse_llm(self):
            from PySide6.QtWidgets import QFileDialog
            # Mở hộp thoại chọn file, lọc hiển thị các file .gguf
            file_path, _ = QFileDialog.getOpenFileName(
                self, "Chọn file mô hình GGUF", "", "GGUF Files (*.gguf);;All Files (*)"
            )
            if file_path:
                file_path = file_path.replace("\\", "/")  # Chuẩn hóa đường dẫn
                # Thêm đường dẫn vào danh sách nếu chưa có
                if self.llm_combo.findText(file_path) == -1:
                    self.llm_combo.addItem(file_path)
                # Cập nhật ô text hiện tại
                self.llm_combo.setCurrentText(file_path)

    # ── Model loader thread ───────────────────
    class Loader(QThread):
        status  = Signal(str)
        ready   = Signal()
        failed  = Signal(str)
        def __init__(self, pipeline):
            super().__init__(); self.pipeline = pipeline
        def run(self):
            try:
                self.pipeline._status_cb = lambda m: self.status.emit(m)
                self.pipeline.load_models()
                self.ready.emit()
            except Exception as e:
                self.failed.emit(str(e))

    # ── Main overlay window ───────────────────
    class OverlayWindow(QWidget):
        sig_result             = Signal(str, str, str, dict)  # orig, trans, lang, timing
        sig_live_transcription = Signal(str, str)             # live text, lang
        sig_draft_translation  = Signal(str)                  # draft trans (speculative)
        sig_status             = Signal(str)
        sig_original_commit = Signal(str)
        sig_stable_live = Signal(str, str)

        def __init__(self, init_args):
            super().__init__()

            # Frameless, always-on-top, tool window (no taskbar)
            self.setWindowFlags(
                Qt.FramelessWindowHint |
                Qt.WindowStaysOnTopHint |
                Qt.Tool
            )
            self.setAttribute(Qt.WA_TranslucentBackground)
            self.setMinimumSize(500, 160)
            self.resize(860, 260)

            self._drag_pos: QPoint | None = None
            self._recording  = False
            self._stream     = None
            self._pyaudio    = None
            self._audio_src  = "Micro"
            self._pipeline   = None
            self._loader     = None
            self._proc_thread= None
            self._audio_q: queue.Queue = queue.Queue()
            self._init_args  = init_args
            self._settings_visible = False

            # Rolling buffer state (2-track)
            self._live_text   = ""   # current live transcription (updates rapidly)
            self._pending_for_translation = ""  # text waiting for sentence boundary
            self._last_commit_time = 0.0

            self._build_ui()
            self.sig_result.connect(self._on_result)
            self.sig_live_transcription.connect(self._on_live_transcription)
            self.sig_draft_translation.connect(self._on_draft_translation)
            self.sig_status.connect(self._set_status)
            self.sig_original_commit.connect(lambda t: self.p_orig.commit(t))
            self.sig_stable_live.connect(self._on_stable_live)  # ← THÊM DÒNG NÀY

            # ── Session transcript log ────────────────────────────────
            self._session_start  = datetime.now()
            self._transcript_log: list[dict] = []
            self._transcripts_dir = os.path.join(
                os.path.expanduser("~"), "Documents", "Transcripts")
            os.makedirs(self._transcripts_dir, exist_ok=True)

            # ── Speculative translation state ─────────────────────────
            # Separate queue for draft (low-priority, cancelable)
            self._draft_q: queue.Queue = queue.Queue(maxsize=1)
            self._draft_thread: threading.Thread | None = None

            self._load_pipeline()

            self._whisper_q: queue.Queue = queue.Queue(maxsize=1)
            self._whisper_result: tuple = ("", "")
            self._whisper_thread: threading.Thread | None = None
            self._stable_buf: StableTranscriptBuffer = StableTranscriptBuffer(confirm_runs=2)

        # ── Build UI ──────────────────────────
        def _build_ui(self):
            # Outer container with rounded border
            outer = QVBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(0)

            self._container = QFrame()
            self._container.setObjectName("container")
            self._container.setStyleSheet(f"""
                QFrame#container {{
                    background: rgba(13,17,23,220);
                    border: 1px solid {BORDER};
                    border-radius: 10px;
                }}
            """)
            outer.addWidget(self._container)

            main = QVBoxLayout(self._container)
            main.setContentsMargins(10, 8, 10, 8)
            main.setSpacing(5)

            # ── Title / drag bar ──────────────
            title_row = QHBoxLayout(); title_row.setSpacing(6)

            # Dot indicator
            self._dot = QLabel("●")
            self._dot.setStyleSheet(f"QLabel{{color:{MUTED};font-size:10px;}}")
            title_row.addWidget(self._dot)

            title_lbl = QLabel("Translator")
            title_lbl.setStyleSheet(
                f"QLabel{{color:{MUTED};font-size:10px;font-weight:600;"
                f"letter-spacing:1px;}}")
            title_row.addWidget(title_lbl)

            title_row.addStretch()

            # Language selectors (always visible)
            def lbl(t):
                l = QLabel(t); l.setStyleSheet(LBL_SM); return l

            title_row.addWidget(lbl("Src:"))
            self.src_lang = QComboBox()
            self.src_lang.addItems(["Auto-detect"] + sorted(LANG_NAMES.values()))
            _set_combo_by_code(self.src_lang, self._init_args.source_lang)
            self.src_lang.setStyleSheet(COMBO_SM)
            title_row.addWidget(self.src_lang)

            title_row.addWidget(lbl("→"))
            self.tgt_lang = QComboBox()
            self.tgt_lang.addItems(sorted(LANG_NAMES.values()))
            _set_combo_by_code(self.tgt_lang, self._init_args.target_lang)
            self.tgt_lang.setStyleSheet(COMBO_SM)
            title_row.addWidget(self.tgt_lang)

            # ⚙ Settings toggle
            self.settings_btn = QPushButton("⚙")
            self.settings_btn.setFixedSize(28, 28)
            self.settings_btn.setStyleSheet(
                f"QPushButton{{background:transparent; color:{MUTED}; border:none; font-size:16px; padding:0px; border-radius:4px;}}"
                f"QPushButton:hover{{background:{BG2}; color:{TEXT};}}"
            )
            self.settings_btn.setToolTip("Settings")
            self.settings_btn.clicked.connect(self._toggle_settings)
            title_row.addWidget(self.settings_btn)

            # 📋 Copy translation
            copy_btn = QPushButton("⎘")
            copy_btn.setFixedSize(28, 28)
            copy_btn.setStyleSheet(
                f"QPushButton{{background:transparent; color:{MUTED}; border:none; font-size:16px; padding:0px;}}"
                f"QPushButton:hover{{background:{BG2}; color:{TEXT}; border-radius:4px;}}"
            )
            copy_btn.setToolTip("Copy translation to clipboard")
            copy_btn.clicked.connect(self._copy_translation)
            title_row.addWidget(copy_btn)

            # 📁 Open transcripts folder
            folder_btn = QPushButton("📁")
            folder_btn.setFixedSize(28, 28)
            folder_btn.setStyleSheet(
                f"QPushButton{{background:transparent; color:{MUTED}; border:none; font-size:16px; padding:0px;}}"
                f"QPushButton:hover{{background:{BG2}; color:{TEXT}; border-radius:4px;}}"
            )
            folder_btn.setToolTip("Open transcripts folder")
            folder_btn.clicked.connect(self._open_transcripts_folder)
            title_row.addWidget(folder_btn)

            # ▶ Start / ■ Stop
            self.rec_btn = QPushButton("▶  Start")
            self.rec_btn.setFixedHeight(28)
            self.rec_btn.setMinimumWidth(72)
            self.rec_btn.setEnabled(False)
            self.rec_btn.setStyleSheet(BTN_SM.format(
                bg=GRN_BG, fg="#86efac", br=GRN_BR, hv="#166534"))
            self.rec_btn.clicked.connect(self._toggle)
            title_row.addWidget(self.rec_btn)

            # Clear + Save
            clr = QPushButton("✕")
            clr.setFixedSize(28, 28)
            clr.setStyleSheet(BTN_SM.format(
                bg="transparent", fg=MUTED, br="transparent", hv=BG2))
            clr.setToolTip("Clear (auto-saves first)")
            clr.clicked.connect(self._clear)
            title_row.addWidget(clr)

            # Close
            close_btn = QPushButton("×")
            close_btn.setFixedSize(28, 28)
            close_btn.setStyleSheet(
                "QPushButton{background:transparent;color:#8b949e;"
                "border:none;font-size:16px;font-weight:bold;}"
                "QPushButton:hover{color:#f87171;}")
            close_btn.clicked.connect(self.close)
            title_row.addWidget(close_btn)

            main.addLayout(title_row)

            # ── Settings panel (collapsible) ──
            self._settings = SettingsPanel(self._init_args, HAS_WASAPI)
            self._settings.reload_btn.clicked.connect(self._load_pipeline)
            self._settings.src_combo.currentTextChanged.connect(
                lambda t: setattr(self, "_audio_src", t))
            self._settings.setVisible(False)
            main.addWidget(self._settings)

            # Connect language selectors → update panel labels live
            self.src_lang.currentTextChanged.connect(self._update_panel_labels)
            self.tgt_lang.currentTextChanged.connect(self._update_panel_labels)

            # ── Waveform ──────────────────────
            self.waveform = MiniWaveform()
            main.addWidget(self.waveform)

            # ── Text panels side by side ──────
            panels_row = QHBoxLayout(); panels_row.setSpacing(8)

            def accent_panel(label, accent, dim_history=True):
                w = QWidget()
                w.setStyleSheet(
                    f"QWidget{{background:rgba(13,17,23,200);"
                    f"border:1px solid {BORDER};border-radius:8px;}}")
                l = QVBoxLayout(w)
                l.setContentsMargins(0, 0, 0, 0)
                l.setSpacing(0)
                # Top accent bar (3px)
                bar = QWidget(); bar.setFixedHeight(3)
                bar.setStyleSheet(
                    f"QWidget{{background:{accent};"
                    f"border-radius:8px 8px 0 0;}}")
                l.addWidget(bar)
                p = SubtitlePanel(label, accent, dim_history)
                l.addWidget(p, stretch=1)
                return w, p

            src_name = LANG_NAMES.get(
                LANG_DISPLAY.get(self.src_lang.currentText(), "en"), "Original")
            tgt_name = LANG_NAMES.get(
                LANG_DISPLAY.get(self.tgt_lang.currentText(), "vi"), "Translation")

            orig_frame, self.p_orig  = accent_panel(src_name,  BLUE,  True)
            trans_frame, self.p_trans = accent_panel(tgt_name, GREEN, False)
            panels_row.addWidget(orig_frame)
            panels_row.addWidget(trans_frame)
            main.addLayout(panels_row, stretch=1)

            # ── Status bar ────────────────────
            self.status_lbl = QLabel("Initializing…")
            self.status_lbl.setStyleSheet(
                f"QLabel{{color:{MUTED};font-size:9px;padding:1px 0;}}")
            main.addWidget(self.status_lbl)

            # ── Resize grip ───────────────────
            grip_row = QHBoxLayout()
            grip_row.addStretch()
            grip = QSizeGrip(self)
            grip.setStyleSheet(f"QSizeGrip{{color:{MUTED};}}")
            grip_row.addWidget(grip)
            main.addLayout(grip_row)

        def _toggle_settings(self):
            self._settings_visible = not self._settings_visible
            self._settings.setVisible(self._settings_visible)

            # Cập nhật style của nút ⚙ tùy theo trạng thái Đóng/Mở
            bg_color = BG2 if self._settings_visible else "transparent"
            fg_color = TEXT if self._settings_visible else MUTED
            border_css = f"border:1px solid {BORDER};" if self._settings_visible else "border:none;"

            self.settings_btn.setStyleSheet(
                f"QPushButton{{background:{bg_color}; color:{fg_color}; {border_css} font-size:16px; padding:0px; border-radius:4px;}}"
                f"QPushButton:hover{{background:{BG2}; color:{TEXT};}}"
            )

            if self._settings_visible:
                # Grow: add settings panel height
                extra = self._settings.sizeHint().height() + 6
                self.resize(self.width(), self.height() + extra)
            else:
                # Shrink back: subtract settings panel height
                extra = self._settings.sizeHint().height() + 6
                self.resize(self.width(), max(180, self.height() - extra))

        def _update_panel_labels(self):
            """Update speaker labels in panels when language selector changes."""
            src_name = LANG_NAMES.get(
                LANG_DISPLAY.get(self.src_lang.currentText(), "en"), "Original")
            tgt_name = LANG_NAMES.get(
                LANG_DISPLAY.get(self.tgt_lang.currentText(), "vi"), "Translation")
            self.p_orig._spk_lbl.setText(src_name)
            self.p_trans._spk_lbl.setText(tgt_name)

        # ── Drag to move ──────────────────────
        def mousePressEvent(self, e):
            if e.button() == Qt.LeftButton:
                self._drag_pos = e.globalPosition().toPoint() - self.pos()

        def mouseMoveEvent(self, e):
            if self._drag_pos and e.buttons() & Qt.LeftButton:
                self.move(e.globalPosition().toPoint() - self._drag_pos)

        def mouseReleaseEvent(self, e):
            self._drag_pos = None

        # ── Opacity slider on scroll ──────────
        def wheelEvent(self, e):
            delta = e.angleDelta().y()
            op = max(0.3, min(1.0, self.windowOpacity() + delta / 1200))
            self.setWindowOpacity(op)

        # ── Pipeline ──────────────────────────
        def _unload_pipeline(self):
            if self._pipeline is None:
                return
            try:
                import torch, gc

                # 1. Dừng loader thread cũ trước tiên
                if self._loader and self._loader.isRunning():
                    self._loader.quit()
                    self._loader.wait(3000)  # chờ tối đa 3s

                # THÊM MỚI: Xóa hẳn liên kết để Python dọn rác VRAM
                if self._loader:
                    self._loader.pipeline = None
                    self._loader = None

                # 2. Gửi poison pill VÀ join trans_thread
                if self._pipeline._trans_thread and self._pipeline._trans_thread.is_alive():
                    try:
                        self._pipeline._trans_q.put_nowait(None)
                    except Exception:
                        pass
                    self._pipeline._trans_thread.join(timeout=2.0)  # ← thêm join

                # 3. Xóa LLM
                if self._pipeline.llm_model_obj is not None:
                    if hasattr(self._pipeline.llm_model_obj, 'close'):
                        try:
                            self._pipeline.llm_model_obj.close()
                        except Exception:
                            pass
                    # Với HF + accelerate: xóa dispatch hooks
                    if hasattr(self._pipeline.llm_model_obj, '_hf_hook'):
                        from accelerate.hooks import remove_hook_from_module
                        remove_hook_from_module(
                            self._pipeline.llm_model_obj, recurse=True)
                    del self._pipeline.llm_model_obj
                    self._pipeline.llm_model_obj = None

                if self._pipeline.llm_tokenizer is not None:
                    del self._pipeline.llm_tokenizer
                    self._pipeline.llm_tokenizer = None

                if self._pipeline.whisper is not None:
                    del self._pipeline.whisper
                    self._pipeline.whisper = None

                del self._pipeline
                self._pipeline = None

                # 4. Dọn VRAM — SỬA LẠI: Gọi gc.collect() 2 lần để xử lý tham chiếu vòng
                gc.collect()
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.synchronize()
                    torch.cuda.empty_cache()
                    torch.cuda.ipc_collect()  # ← Dọn dẹp bộ nhớ chia sẻ

                self._set_status("GPU VRAM cleared.")
            except Exception as e:
                self._set_status(f"Cleanup warning: {e}")

        def _load_pipeline(self):
            if self._recording: self._stop_recording()
            self.rec_btn.setEnabled(False)

            # ── Giải phóng VRAM trước ──
            self._set_status("Unloading previous model…")
            self._unload_pipeline()

            sp = self._settings
            self._pipeline = LocalPipeline(
                source_lang   = LANG_DISPLAY.get(self.src_lang.currentText(), "auto"),
                target_lang   = LANG_DISPLAY.get(self.tgt_lang.currentText(), "vi"),
                whisper_model = sp.w_model.currentText(),
                llm_model     = sp.llm_combo.currentText(),
                device        = sp.dev_combo.currentText(),
                compute_type  = "float16" if sp.dev_combo.currentText()=="cuda" else "int8",
                result_callback = lambda *a: self.sig_result.emit(*a),
                status_callback = lambda m: self.sig_status.emit(m),
            )
            self._loader = Loader(self._pipeline)
            self._loader.status.connect(self._set_status)
            self._loader.ready.connect(self._on_ready)
            self._loader.failed.connect(
                lambda e: self._set_status(f"❌ {e}"))
            self._loader.start()

        def _on_ready(self):
            self.rec_btn.setEnabled(True)
            sp = self._settings
            self._set_status(
                f"✓ Ready  {sp.w_model.currentText()} + "
                f"{sp.llm_combo.currentText().split('/')[-1]}  [{sp.dev_combo.currentText()}]")

        # ── Recording ─────────────────────────
        def _toggle(self):
            if not self._recording: self._start_recording()
            else: self._stop_recording()

        def _start_recording(self):
            if not self._pipeline or not self._pipeline._models_ready.is_set():
                return
            src_code = LANG_DISPLAY.get(self.src_lang.currentText(), "auto")
            tgt_code = LANG_DISPLAY.get(self.tgt_lang.currentText(), "vi")
            self._pipeline.source_lang      = src_code
            self._pipeline.target_lang      = tgt_code
            self._pipeline.source_lang_name = LANG_NAMES.get(src_code, src_code.capitalize())
            self._pipeline.target_lang_name = LANG_NAMES.get(tgt_code, tgt_code.capitalize())
            self._pipeline.prev_text        = ""
            self._pipeline.context_history  = []

            self._recording = True
            while not self._audio_q.empty():
                try: self._audio_q.get_nowait()
                except: break

            # Start draft translation worker
            self._draft_thread = threading.Thread(
                target=self._draft_worker, daemon=True)
            self._draft_thread.start()

            ###
            self._whisper_thread = threading.Thread(
                target=self._whisper_worker, daemon=True)
            self._whisper_thread.start()

            self.rec_btn.setText("■  Stop")
            self.rec_btn.setStyleSheet(BTN_SM.format(
                bg=RED_BG, fg="#fca5a5", br=RED_BR, hv="#991b1b"))
            self._dot.setStyleSheet(
                f"QLabel{{color:{GREEN};font-size:10px;}}")
            self.waveform.start()

            self._proc_thread = threading.Thread(
                target=self._audio_loop, daemon=True)
            self._proc_thread.start()

            try:
                src = self._settings.src_combo.currentText()
                self._audio_src = src
                if src == "Micro":
                    self._stream = sd.InputStream(
                        samplerate=16000, channels=1, dtype=np.float32,
                        blocksize=int(16000*0.3), callback=self._cb_micro)
                    self._stream.start()
                    self._set_status("● Micro")
                else:
                    self._start_wasapi()
                    self._set_status("● WASAPI")
            except Exception as e:
                self._recording = False
                self.rec_btn.setText("▶  Start")
                self.rec_btn.setStyleSheet(BTN_SM.format(
                    bg=GRN_BG, fg="#86efac", br=GRN_BR, hv="#166534"))
                self._dot.setStyleSheet(
                    f"QLabel{{color:{MUTED};font-size:10px;}}")
                self.waveform.stop()
                self._set_status(f"Error: {e}")

        def _start_wasapi(self):
            self._pyaudio = pyaudio.PyAudio()
            info = self._pyaudio.get_host_api_info_by_type(pyaudio.paWASAPI)
            spk  = self._pyaudio.get_device_info_by_index(info["defaultOutputDevice"])
            if not spk["isLoopbackDevice"]:
                for lb in self._pyaudio.get_loopback_device_info_generator():
                    if spk["name"] in lb["name"]: spk = lb; break
            self._wasapi_rate = int(spk["defaultSampleRate"])
            self._stream = self._pyaudio.open(
                format=pyaudio.paInt16, channels=2,
                rate=self._wasapi_rate, input=True,
                input_device_index=spk["index"],
                frames_per_buffer=int(16000*0.3),
                stream_callback=self._cb_wasapi)
            self._stream.start_stream()

        def _stop_recording(self):
            self._recording = False  # draft_worker sẽ tự thoát vì check _recording
            self.rec_btn.setText("▶  Start")
            self.rec_btn.setStyleSheet(BTN_SM.format(
                bg=GRN_BG, fg="#86efac", br=GRN_BR, hv="#166534"))
            self._dot.setStyleSheet(
                f"QLabel{{color:{MUTED};font-size:10px;}}")
            self.waveform.stop()
            try:
                if self._stream:
                    if self._audio_src == "Micro":
                        if self._stream.active: self._stream.stop()
                        self._stream.close()
                    else:
                        self._stream.stop_stream(); self._stream.close()
                        self._pyaudio.terminate()
                    self._stream = None
            except Exception as e:
                print(f"[stop] {e}")
            # Chờ threads dừng — timeout ngắn, không block lâu
            for t in [self._proc_thread, self._draft_thread, self._whisper_thread]:
                if t and t.is_alive():
                    t.join(timeout=1.5)
            self._save_transcript()
            self._set_status("Stopped.")
            self._stable_buf.reset()

        # ── Audio callbacks ───────────────────
        def _cb_micro(self, indata, frames, c_time, status):
            self._audio_q.put_nowait(indata.copy().flatten())
            self.waveform.push(indata.flatten())

        def _cb_wasapi(self, in_data, frame_count, time_info, status):
            audio = np.frombuffer(in_data, dtype=np.int16).astype(np.float32)/32768.0
            if HAS_SCIPY:
                n = int(len(audio)*16000/self._wasapi_rate)
                audio = scipy_resample(audio, n)
            audio = audio.reshape(-1,2).mean(axis=1)
            self._audio_q.put_nowait(audio)
            self.waveform.push(audio)
            return (None, pyaudio.paContinue)

        # ── Audio → pipeline (VAD + Speculative Translation) ──
        def _audio_loop(self):
            """
            THREE-TIER strategy:

            Tier 1 — Live ASR preview (every 0.5s, last 4s):
              Shows transcription updating in real-time.

            Tier 2 — Speculative translation (every ~2.5s during speech):
              While person is still speaking, sends current partial
              transcript → shows DRAFT translation (italic, dimmed ✦).
              Draft is REPLACED when final translation arrives.

            Tier 3 — Final translation (on VAD silence):
              Full utterance → LLM → final translation replaces draft.
            """
            PREVIEW_INTERVAL  = 0.5    # live ASR every 0.5s
            SPECULATIVE_EVERY = 2.5    # draft translation every 2.5s during speech
            MAX_UTTERANCE_S   = 12
            MIN_COMMIT_CHARS  = 8
            SILENCE_AFTER_S   = 1.2
            PREVIEW_BUF_S     = 4.0

            p  = self._pipeline
            sr = 16000

            buf              = np.array([], dtype=np.float32)
            utterance_start  = time.time()
            last_speech_t    = time.time()
            last_preview     = time.time()   # ← FIX: tránh UnboundLocalError
            last_speculative = time.time()
            last_live_text   = ""
            committed_text   = ""
            last_spec_text   = ""

            self._stable_buf.reset()
            self._whisper_result = ("", "")


            while self._recording:
                # ── Drain audio queue ────────────────────────────────
                for _ in range(12):
                    try:
                        c = self._audio_q.get_nowait()
                        chunk = c.astype(np.float32)
                        buf = np.concatenate([buf, chunk])
                        if len(buf) > int(MAX_UTTERANCE_S * sr):
                            buf = buf[-int(MAX_UTTERANCE_S * sr):]
                        # ← THÊM LẠI: cập nhật VAD dựa trên RMS
                        if np.sqrt(np.mean(chunk ** 2)) > 0.005:
                            last_speech_t = time.time()
                    except queue.Empty:
                        break
                try:
                    c = self._audio_q.get(timeout=0.08)
                    chunk = c.astype(np.float32)
                    buf = np.concatenate([buf, c.astype(np.float32)])
                    if np.sqrt(np.mean(chunk ** 2)) > 0.005:  # ← THÊM
                        last_speech_t = time.time()  # ← THÊM
                except queue.Empty:
                    pass

                now = time.time()
                if len(buf) > int(MAX_UTTERANCE_S * sr):
                    buf = buf[-int(MAX_UTTERANCE_S * sr):]
                if len(buf) < sr * 0.4:
                    continue

                # ─── Tier 1: Live ASR preview (NON-BLOCKING) ─────────────
                if now - last_preview >= PREVIEW_INTERVAL:
                    last_preview = now

                    # SỬA LẠI DÒNG NÀY: Đưa toàn bộ buf vào thay vì cắt 4s
                    prev_buf = buf

                    if np.sqrt(np.mean(prev_buf ** 2)) > 0.003:
                        pcm = (np.clip(prev_buf, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
                        # ← Đẩy vào queue thay vì gọi trực tiếp
                        if self._whisper_q.empty():  # chỉ push nếu worker rảnh
                            self._whisper_q.put_nowait(pcm)
                        # Cập nhật last_live_text từ result của whisper_thread
                        cached = self._whisper_result
                        if cached[0] and cached[0] != last_live_text:
                            last_live_text = cached[0]

                # ─── Tier 2: Speculative translation ─────────────────
                if (now - last_speculative >= SPECULATIVE_EVERY
                        and now - last_speech_t < SILENCE_AFTER_S
                        and last_live_text
                        and last_live_text != last_spec_text
                        and len(last_live_text) >= MIN_COMMIT_CHARS):
                    last_speculative = now
                    last_spec_text   = last_live_text
                    self._queue_draft(p, last_live_text)

                # ─── Tier 3: Final commit on VAD silence ─────────────
                should_commit = (
                        (now - last_speech_t >= SILENCE_AFTER_S and len(buf) >= sr)
                        or (now - utterance_start >= MAX_UTTERANCE_S)
                )
                if should_commit:
                    if np.sqrt(np.mean(buf ** 2)) > 0.003 and len(buf) >= sr:
                        pcm = (np.clip(buf, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
                        wp = p._save_wav(pcm)
                        try:
                            full_text, lang = p._transcribe(wp)
                        finally:
                            try:
                                os.unlink(wp)
                            except OSError:
                                pass

                        if full_text and len(full_text) >= MIN_COMMIT_CHARS:
                            new_part = full_text
                            if committed_text:
                                import difflib
                                ow = committed_text.split()
                                nw = full_text.split()
                                new_only = []
                                for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ow, nw).get_opcodes():
                                    if tag in ("insert", "replace"):
                                        new_only.extend(nw[j1:j2])
                                new_part = " ".join(new_only).strip()

                            if new_part and len(new_part) >= MIN_COMMIT_CHARS:
                                # 1. CHỐT CÂU GỐC LÊN GIAO DIỆN NGAY LẬP TỨC (Không đợi LLM)
                                self.sig_original_commit.emit(full_text)

                                # Cancel pending draft — final is coming
                                while not self._draft_q.empty():
                                    try:
                                        self._draft_q.get_nowait()
                                    except queue.Empty:
                                        break

                                # 2. QUĂNG CHO LLM DỊCH
                                self._queue_translation(p, new_part, now)
                                committed_text = full_text

                    # 3. RESET TOÀN BỘ TRÍ NHỚ ĐỂ ĐÓN CÂU MỚI SẠCH SẼ
                    buf              = np.array([], dtype=np.float32)
                    utterance_start  = now
                    last_speech_t    = now
                    last_preview     = now   # ← THÊM
                    last_live_text   = ""
                    committed_text   = ""
                    last_spec_text   = ""
                    last_speculative = now
                    self._stable_buf.reset()
                    self._whisper_result = ("", "")

        def _queue_draft(self, p, text: str):
            """Push speculative text — single-slot, always replaces old."""
            text = text.strip()
            if not text or len(text) < 4:
                return
            while not self._draft_q.empty():
                try: self._draft_q.get_nowait()
                except queue.Empty: break
            self._draft_q.put_nowait((text, p.source_lang))

        def _queue_translation(self, p, text: str, t_start: float):
            """Push a complete utterance to the final LLM queue."""
            text = text.strip()
            if not text or len(text) < 2:
                return
            if p._trans_q.full():
                try: p._trans_q.get_nowait()
                except queue.Empty: pass
            p._trans_q.put_nowait((text, p.source_lang, 0.0, t_start))

        # ── Result / status ───────────────────
        def _draft_worker(self):
            """
            Background thread for speculative (Tier 2) translation.
            Picks from _draft_q, translates, emits sig_draft_translation.
            Lower priority than final translation — if final arrives first, draft is discarded.
            """
            p = self._pipeline
            while self._recording:
                try:
                    item = self._draft_q.get(timeout=0.5)
                except queue.Empty:
                    continue
                if item is None:
                    break
                text, lang = item
                try:
                    # draft = p._translate(text)
                    draft = p._translate(text, max_tokens=80)
                    if draft and self._recording:
                        self.sig_draft_translation.emit(draft)
                except Exception:
                    pass

        def _on_draft_translation(self, draft: str):
            """Show speculative draft in translation panel."""
            self.p_trans.set_draft(draft)

        def _on_live_transcription(self, text: str, lang: str):
            """Tier 1: update Original panel live, no commit."""
            self.p_orig.set_live(text, lang)

        def _on_stable_live(self, confirmed: str, provisional: str):
            """Cập nhật giao diện với 2 màu chữ."""
            self.p_orig.set_live_stable(confirmed, provisional)

        def _on_result(self, orig: str, trans: str, lang: str, timing: dict):
            """Tier 3: LLM finished → commit, log entry."""
            # CÂU GỐC ĐÃ ĐƯỢC CHỐT Ở TIER 3 TRƯỚC ĐÓ RỒI, CHỈ CẦN CHỐT BẢN DỊCH VÀO P_TRANS
            if trans.strip():
                self.p_trans.append(trans)
                self._transcript_log.append({
                    "ts": datetime.now().strftime("%H:%M:%S"),
                    "orig": orig,
                    "trans": trans,
                })
            else:
                # Nếu dịch lỗi, ghi chú vào bảng bên phải để giữ 2 bảng đồng đều độ dài
                self.p_trans.append(f"[Lỗi dịch] {orig[:30]}...")

            tgt = self.tgt_lang.currentText()
            self._set_status(
                f"● ASR live  LLM {timing['translate']}s  {lang}→{tgt[:2]}")

        def _set_status(self, msg: str):
            self.status_lbl.setText(msg)

        def _save_transcript(self):
            """Save current session to a .md file. Returns filepath or None."""
            if not self._transcript_log:
                return None
            sp = self._settings
            src = self.src_lang.currentText()
            tgt = self.tgt_lang.currentText()
            model_asr = sp.w_model.currentText()
            model_llm = sp.llm_combo.currentText().split("/")[-1]
            ts_start  = self._session_start.strftime("%Y-%m-%d_%H-%M-%S")
            fname     = f"transcript_{ts_start}.md"
            fpath     = os.path.join(self._transcripts_dir, fname)

            lines = [
                f"# Transcript — {self._session_start.strftime('%Y-%m-%d %H:%M:%S')}",
                f"",
                f"| Field | Value |",
                f"|-------|-------|",
                f"| Source | {src} |",
                f"| Target | {tgt} |",
                f"| ASR model | {model_asr} |",
                f"| LLM model | {model_llm} |",
                f"| Saved | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} |",
                f"",
                f"---",
                f"",
            ]
            for entry in self._transcript_log:
                lines.append(f"**[{entry['ts']}]** {entry['orig']}")
                lines.append(f"> {entry['trans']}")
                lines.append("")

            try:
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
                self._set_status(f"✓ Saved → {fname}")
                return fpath
            except Exception as ex:
                self._set_status(f"Save error: {ex}")
                return None

        def _copy_translation(self):
            """Copy all translation lines to clipboard."""
            if not self._transcript_log:
                self._set_status("Nothing to copy.")
                return
            text = "\n".join(e["trans"] for e in self._transcript_log if e["trans"])
            QApplication.clipboard().setText(text)
            self._set_status(f"✓ Copied {len(self._transcript_log)} lines.")

        def _open_transcripts_folder(self):
            """Open the transcripts folder in file explorer."""
            import subprocess
            try:
                if sys.platform == "win32":
                    os.startfile(self._transcripts_dir)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", self._transcripts_dir])
                else:
                    subprocess.Popen(["xdg-open", self._transcripts_dir])
            except Exception as ex:
                self._set_status(f"Cannot open folder: {ex}")

        def _clear(self):
            """Save current session then clear panels."""
            self._save_transcript()
            self.p_orig.clear(); self.p_trans.clear()
            self._transcript_log.clear()
            self._session_start = datetime.now()
            self._live_text = ""
            self._pending_for_translation = ""

        # def closeEvent(self, e):
        #     if self._recording: self._stop_recording()
        #     self._save_transcript()
        #     self._unload_pipeline()
        #     e.accept()
        #     QApplication.quit()

        def closeEvent(self, e):
            if self._recording: self._stop_recording()
            self._save_transcript()
            e.accept()
            import os
            os._exit(0)

        def _whisper_worker(self):
            """Thread riêng cho Tier 1 Whisper — với stable buffer chống nhảy chữ."""
            p = self._pipeline
            while self._recording:
                try:
                    pcm = self._whisper_q.get(timeout=0.3)
                except queue.Empty:
                    continue
                if pcm is None:
                    break
                wp = p._save_wav(pcm)
                try:
                    # Dùng confirmed text làm anchor hint cho Whisper
                    prompt = self._stable_buf.confirmed
                    raw_text, lang = p._transcribe_fast(wp, initial_prompt=prompt)
                    if raw_text:
                        confirmed, provisional = self._stable_buf.update(raw_text)
                        display_text = confirmed
                        if provisional:
                            display_text = confirmed + (" " if confirmed else "") + provisional
                        self._whisper_result = (display_text, lang)
                        self.sig_stable_live.emit(confirmed, provisional)
                except Exception:
                    pass
                finally:
                    try:
                        os.unlink(wp)
                    except OSError:
                        pass

    # ── helpers ──────────────────────────────
    def _set_combo_by_code(combo, code):
        name = LANG_NAMES.get(code)
        if name:
            idx = combo.findText(name)
            if idx >= 0: combo.setCurrentIndex(idx)

    # ── Launch ────────────────────────────────
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    pal = QPalette()
    for role, color in [
        (QPalette.Window,          QColor(13,17,23)),
        (QPalette.WindowText,      QColor(230,237,243)),
        (QPalette.Base,            QColor(13,17,23)),
        (QPalette.AlternateBase,   QColor(22,27,34)),
        (QPalette.Text,            QColor(230,237,243)),
        (QPalette.Button,          QColor(22,27,34)),
        (QPalette.ButtonText,      QColor(230,237,243)),
        (QPalette.Highlight,       QColor(31,111,235)),
        (QPalette.HighlightedText, QColor(255,255,255)),
    ]:
        pal.setColor(role, color)
    app.setPalette(pal)

    win = OverlayWindow(args)
    # Default position: bottom-center of primary screen
    screen = app.primaryScreen().geometry()
    win.move(
        (screen.width() - win.width()) // 2,
        screen.height() - win.height() - 60
    )
    win.show()
    sys.exit(app.exec())


# ═════════════════════════════════════════════════════════════════
# Entry point
# ═════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Local STT + Translation pipeline (GUI by default)",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--no-gui",        action="store_true")
    parser.add_argument("--test",          action="store_true")
    parser.add_argument("--test-file",     default="test.wav")
    parser.add_argument("--source-lang",   default="en")
    parser.add_argument("--target-lang",   default="vi")
    parser.add_argument("--whisper-model", default="base",
        choices=["tiny","base","small","medium","large-v2","large-v3","large-v3-turbo"])
    parser.add_argument("--llm-model",     default="C:/Users/qt321/realtime_transcription/translategemma-4b-it-Q4_K_M_GGUF.gguf")
    parser.add_argument("--device",        default="cuda", choices=["cuda","cpu"])
    parser.add_argument("--compute-type",  default="float16",
        choices=["float16","int8","float32"])
    parser.add_argument("--chunk-seconds", type=int, default=7)
    parser.add_argument("--stride-seconds",type=int, default=5)
    args = parser.parse_args()

    # ── GUI (default) ────────────────────────
    if not args.no_gui and not args.test:
        run_gui(args)
        return

    # ── CLI / test ───────────────────────────
    def on_result(orig, trans, lang, timing):
        emit_json({"type":"result","original":orig,"translated":trans,
                   "language":lang,"timing":timing})

    pipeline = LocalPipeline(
        source_lang    = args.source_lang,
        target_lang    = args.target_lang,
        whisper_model  = args.whisper_model,
        llm_model      = args.llm_model,
        device         = args.device,
        compute_type   = args.compute_type,
        chunk_seconds  = args.chunk_seconds,
        stride_seconds = args.stride_seconds,
        result_callback = on_result,
    )
    emit_json({"type": "status", "message": "Loading models…"})
    pipeline.load_models()
    emit_json({"type": "ready"})

    if args.test:
        log(f"Test mode: {args.test_file}")
        with wave.open(args.test_file, "r") as wf:
            pcm = wf.readframes(wf.getnframes())
        pos = 0
        while pos + pipeline.chunk_bytes <= len(pcm):
            pipeline.process_chunk(pcm[pos: pos + pipeline.chunk_bytes])
            pos += pipeline.stride_bytes
        if pos < len(pcm) and len(pcm) - pos > pipeline.sample_rate * 2:
            pipeline.process_chunk(pcm[pos:])
    else:
        pipeline.run_stdin()

    emit_json({"type": "done"})


if __name__ == "__main__":
    main()