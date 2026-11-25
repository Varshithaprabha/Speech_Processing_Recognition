"""Part B's core: both directions of the conversation, AI first (Groq / Ollama) and rules as fallback.

Messages follow section 6 of the project doc:
  from: "signer" | "speaker" (| "system" for status/suggestions/summary)
  type: "gloss" | "text" | "speech_partial" | "alert"  (+ additions "suggestions", "summary")
"""
from __future__ import annotations

from collections import deque

from . import config, llm, rules
from .messages import make_message

QUICK_REPLIES = [  # fixed phrase board for the Deaf person (Part C can let users customise it)
    {"id": "yes", "text": "Yes.", "emotion": "neutral"},
    {"id": "no", "text": "No.", "emotion": "neutral"},
    {"id": "wait", "text": "Please wait a moment.", "emotion": "neutral"},
    {"id": "repeat", "text": "Please say that again, slowly.", "emotion": "question"},
    {"id": "write", "text": "Please write it down for me.", "emotion": "neutral"},
    {"id": "understand_not", "text": "I don't understand.", "emotion": "question"},
    {"id": "pain", "text": "I am in pain.", "emotion": "urgent"},
    {"id": "water", "text": "May I have some water, please?", "emotion": "question"},
    {"id": "washroom", "text": "Where is the washroom?", "emotion": "question"},
    {"id": "family", "text": "Please call my family.", "emotion": "urgent"},
    {"id": "thanks", "text": "Thank you.", "emotion": "happy"},
]
QUICK_TRANSLATIONS = {   # so the phrase board works offline in all three languages
    "hi": {"yes": "हाँ।", "no": "नहीं।", "wait": "कृपया एक पल रुकिए।", "repeat": "कृपया फिर से धीरे बोलिए।",
           "write": "कृपया इसे लिखकर दीजिए।", "understand_not": "मुझे समझ नहीं आया।", "pain": "मुझे दर्द हो रहा है।",
           "water": "क्या मुझे थोड़ा पानी मिल सकता है?", "washroom": "शौचालय कहाँ है?",
           "family": "कृपया मेरे परिवार को बुलाइए।", "thanks": "धन्यवाद।"},
    "te": {"yes": "అవును.", "no": "కాదు.", "wait": "దయచేసి ఒక్క క్షణం ఆగండి.", "repeat": "దయచేసి మళ్ళీ నెమ్మదిగా చెప్పండి.",
           "write": "దయచేసి రాసి ఇవ్వండి.", "understand_not": "నాకు అర్థం కాలేదు.", "pain": "నాకు నొప్పిగా ఉంది.",
           "water": "కొంచెం నీళ్ళు ఇస్తారా?", "washroom": "బాత్రూమ్ ఎక్కడ ఉంది?",
           "family": "దయచేసి నా కుటుంబాన్ని పిలవండి.", "thanks": "ధన్యవాదాలు."},
}
SOS = {
    "en": "Emergency! I am Deaf and I need help right now. Please call a doctor.",
    "hi": "आपातकाल! मैं बधिर हूँ और मुझे अभी मदद चाहिए। कृपया डॉक्टर को बुलाइए।",
    "te": "అత్యవసరం! నాకు వినపడదు, నాకు వెంటనే సహాయం కావాలి. దయచేసి డాక్టర్‌ను పిలవండి.",
}


def _emotion_of(text: str) -> str:
    t = text.strip()
    return "question" if t.endswith("?") else ("urgent" if t.endswith("!") else "neutral")


class Conversation:
    def __init__(self):
        self.history: deque[dict] = deque(maxlen=12)   # context for the AI prompts
        self.transcript: list[dict] = []                # every final message, for summary / export
        self.listener_language = "en"                   # language the hearing person speaks
        self.clips = config.avatar_vocab()
        self.suggestions: list[dict] = []               # last smart replies, tapped by id s1..s4

    def _remember(self, m: dict):
        self.history.append(m)
        self.transcript.append(m)
        del self.transcript[:-500]

    def reset(self):
        self.history.clear()
        self.transcript.clear()
        self.suggestions = []

    # ------------------------------------------------------------- signer -> speaker
    @staticmethod
    def _faithful(glosses: list[str], sentence_en: str) -> bool:
        """The AI's sentence may not mention a concept the patient didn't sign (e.g. 'fever' for SICK)."""
        signed = set(glosses)
        said = set(rules.text_to_gloss(sentence_en, set(rules.SIGN_CONCEPTS))) - {"ME", "YOU"}
        if "HOW-ARE-YOU" in signed:
            said -= {"GOOD"}                              # "how are you feeling" / "I'm fine"
        if signed & {"GOOD", "BAD"}:
            said -= {"GOOD", "BAD"}                       # "not well" vs "well" is too fuzzy to check
        if "THANK-YOU" in signed:
            said -= {"GOOD"}
        if "TODAY" not in signed:
            said -= {"TODAY"}                             # "now", "today" are harmless additions
        return not (said - signed)

    async def on_gloss(self, msg: dict) -> dict:
        """Fill `sentence` in a gloss message from sign_service."""
        glosses = msg.get("content", "").split()
        emotion = msg.get("emotion", "neutral")
        out = dict(msg)
        draft = rules.gloss_to_sentence(glosses, emotion)        # grounds the AI and is the fallback
        res = await llm.gloss_to_sentence(glosses, emotion, msg.get("words"), self.listener_language,
                                          list(self.history), draft)
        if res and not self._faithful(glosses, res["sentence_en"]):
            # small models sometimes copy earlier topics: retry once without history, then give up
            res = await llm.gloss_to_sentence(glosses, emotion, msg.get("words"), self.listener_language, [], draft)
            if res and not self._faithful(glosses, res["sentence_en"]):
                res = None
        if res:
            # sign_service saw the face; trust its emotion. The AI may only turn neutral into question.
            emo = res["emotion"] if emotion == "neutral" and res["emotion"] == "question" else emotion
            lang = "en" if res["sentence"].isascii() else self.listener_language   # model may skip translating
            out.update(sentence=res["sentence"], sentence_en=res["sentence_en"], emotion=emo,
                       language=lang, source=res["provider"], draft=draft)
        else:
            out.update(sentence=draft, sentence_en=draft, language="en", source="rules")
        if out["sentence"]:
            self._remember(out)
        return out

    def quick_reply(self, reply_id: str) -> dict | None:
        """Phrase board (ids like 'water') or a smart suggestion (ids s1..s4) tapped by the Deaf user."""
        sug = next((s for s in self.suggestions if s["id"] == reply_id), None)
        if sug:
            text_en, text = sug["text_en"], sug["text"]
            emotion, kind = _emotion_of(text_en), "suggestion"
        else:
            q = next((r for r in QUICK_REPLIES if r["id"] == reply_id), None)
            if not q:
                return None
            text_en = q["text"]
            text = QUICK_TRANSLATIONS.get(self.listener_language, {}).get(reply_id, text_en)
            emotion, kind = q["emotion"], "quick_reply"
        lang = "en" if text.isascii() else self.listener_language
        m = make_message("signer", "text", text_en, text, language=lang, emotion=emotion,
                         sentence_en=text_en, kind=kind, source=kind)
        self._remember(m)
        return m

    def sos(self) -> dict:
        lang = self.listener_language if self.listener_language in SOS else "en"
        m = make_message("signer", "alert", "SOS", SOS[lang], language=lang, emotion="urgent",
                         sentence_en=SOS["en"], kind="sos", source="sos")
        self._remember(m)
        return m

    # ------------------------------------------------------------- speaker -> signer
    @staticmethod
    def _grounded(ai_gloss: list[str], original: str, english: str, allowed: set[str]) -> list[str]:
        """Keep the AI's sign order, but only signs whose words were actually said (in the original or in
        the English caption), and add back any it missed. Stops the avatar signing things nobody said."""
        evidence = rules.text_to_gloss(original, allowed) + rules.text_to_gloss(english, allowed)
        if not evidence:                                  # no keywords found at all: trust the AI
            return ai_gloss
        keep = [g for g in ai_gloss if g in evidence]
        keep += [g for g in dict.fromkeys(evidence) if g not in keep]
        greet = [g for g in rules.GREETINGS if g in keep]          # HELLO, HOW-ARE-YOU, THANK-YOU
        times = [g for g in keep if g in rules.TIMES]
        return greet + times + [g for g in keep if g not in greet and g not in times]

    def partial(self, text: str, language: str = "en", confidence: float = 1.0) -> dict:
        """Live caption while the speaker is still talking (no AI call, so it's instant)."""
        return make_message("speaker", "speech_partial", text, text, language=language,
                            emotion=rules.tone(text), confidence=confidence, source="partial")

    async def on_speaker_text(self, text: str, language: str = "en", confidence: float = 1.0,
                              english_hint: str | None = None, input_: str = "speech") -> dict:
        """Speaker's final words -> caption + tone + avatar gloss/clips."""
        if language in config.LANG_NAMES:
            self.listener_language = language
        allowed = list(self.clips)
        res = await llm.text_to_gloss(text, language, allowed, list(self.history))
        unclear = False
        if res:
            english, emotion, source = res["english"], res["emotion"], res["provider"]
            unclear = res["unclear"] or confidence < 0.35
            gloss = self._grounded(res["gloss"], text, english, set(allowed))
            # check the original too: shouting (CAPS, "!!") is lost in the cleaned-up caption
            tones = {rules.tone(text), rules.tone(english)}
            rule_tone = "urgent" if "urgent" in tones else ("angry" if "angry" in tones else None)
            if rule_tone and emotion != "urgent":                          # never miss an emergency / anger
                emotion = rule_tone
        else:
            english = english_hint or text            # Whisper's translate pass, when non-English
            gloss = rules.text_to_gloss(english, set(allowed))
            emotion, source = rules.tone(english), "rules"
        clips = [{"gloss": g, "video": self.clips[g].get("video", f"{g}.mp4"),
                  "landmarks": self.clips[g].get("landmarks"), "duration": self.clips[g].get("duration")}
                 for g in gloss if g in self.clips]
        m = make_message("speaker", "text", text, english, language=language, emotion=emotion,
                         confidence=confidence, gloss=" ".join(gloss), clips=clips, input=input_, source=source,
                         unclear=unclear)     # Part C: show "?" so the patient can ask them to repeat
        self._remember(m)
        return m

    # ------------------------------------------------------------- smart replies & summary
    async def suggest(self) -> dict:
        """3-4 replies the Deaf user can tap, based on the last few messages."""
        res = await llm.suggest_replies(list(self.history), self.listener_language)
        if res:
            items, source = res["replies"], res["provider"]
        else:
            last = next((h for h in reversed(self.history) if h.get("from") == "speaker"), None)
            items = [{"text_en": t, "text": t} for t in rules.suggest_replies(last)]
            source = "rules"
        self.suggestions = [{"id": f"s{i + 1}", **it} for i, it in enumerate(items[:4])]
        return make_message("system", "suggestions", "", "", language=self.listener_language,
                            suggestions=self.suggestions, source=source)

    async def summary(self) -> dict:
        """Short record of the conversation (e.g. for a doctor visit) + full transcript for export."""
        lines = [{"from": t["from"], "type": t["type"], "text": t.get("sentence_en") or t.get("sentence") or t["content"],
                  "original": t["content"], "emotion": t["emotion"], "timestamp": t["timestamp"]}
                 for t in self.transcript]
        res = await llm.summarize(self.transcript) if self.transcript else None
        if res:
            summary, points, source = res["summary"], res["key_points"], res["provider"]
        else:
            summary, points = rules.summarize(lines), []
            source = "rules"
        return make_message("system", "summary", summary, summary, key_points=points, transcript=lines,
                            source=source)
