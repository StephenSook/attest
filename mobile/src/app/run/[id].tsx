import { useAudioPlayer, useAudioPlayerStatus } from "expo-audio";
import * as Print from "expo-print";
import { shareAsync } from "expo-sharing";
import { useLocalSearchParams } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import VerdictStamp from "../../components/VerdictStamp";
import {
  audioUrlOf,
  fetchAttestation,
  fetchRun,
  transcriptOf,
  type Attestation,
  type RunDetail,
} from "../../lib/api";
import { colors, fonts } from "../../lib/theme";

function certificateHtml(doc: Attestation): string {
  const claims = doc.claims
    .map(
      (claim) => `
      <div style="border-bottom:1px solid #e4e1d6;padding:10px 0">
        <div style="display:flex;justify-content:space-between">
          <span style="font-family:monospace;font-size:11px;text-transform:uppercase;letter-spacing:2px;color:#8a8678">${claim.claim.replaceAll("_", " ")}</span>
          <strong style="font-size:18px">${claim.abstain ? "abstained" : claim.answer}</strong>
        </div>
        <div style="font-family:monospace;font-size:11px;color:#57544b;margin-top:4px">
          ${claim.span ? `supporting span: "${claim.span.text}" (turn ${claim.span.turn}, chars ${claim.span.char_start}-${claim.span.char_end})` : "no supporting span: the system did not answer"}
        </div>
      </div>`,
    )
    .join("");
  return `
  <html><body style="font-family:Georgia,serif;background:#faf9f5;color:#191712;padding:32px">
    <div style="border:2px solid #191712;border-radius:8px;padding:28px;background:#ffffff">
      <div style="font-family:monospace;font-size:11px;text-transform:uppercase;letter-spacing:3px;color:#8a8678">certificate of verification</div>
      <h1 style="margin:6px 0 2px">${doc.org ?? "Verification run"}</h1>
      <div style="font-family:monospace;font-size:11px;color:#8a8678">${doc.run_id} · completed ${doc.completed_at}${doc.replay ? " · replay of a real recorded call" : ""}</div>
      <div style="margin:14px 0;display:inline-block;border:2px solid #c25e00;color:#c25e00;background:#f7e8d8;border-radius:6px;padding:6px 12px;font-family:monospace;text-transform:uppercase;letter-spacing:2px">${doc.reconciliation.verdict} · posterior ${Math.round(doc.reconciliation.posterior_probability * 100)}%</div>
      ${claims}
      <div style="font-family:monospace;font-size:10px;color:#57544b;margin-top:14px;word-break:break-all">
        ${doc.calibration.available ? `abstention gate calibrated at qhat ${doc.calibration.qhat}, target ${Math.round((doc.calibration.target_coverage ?? 0) * 100)}%, measured ${((doc.calibration.empirical_coverage ?? 0) * 100).toFixed(1)}% on held-out data<br/>` : ""}
        payload sha256 ${doc.terminal_payload_sha256}<br/>
        ${doc.signature.signed ? `signature ${doc.signature.alg} ${doc.signature.value}` : "unsigned: no signing key configured on this deployment"}
      </div>
      <div style="font-family:monospace;font-size:10px;color:#8a8678;margin-top:10px">${doc.policy}</div>
    </div>
  </body></html>`;
}

export default function RunScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sharing, setSharing] = useState(false);

  useEffect(() => {
    if (!id) return;
    fetchRun(id)
      .then(setDetail)
      .catch(() => setError("Could not load this run. Pull back and retry."));
  }, [id]);

  const turns = useMemo(() => (detail ? transcriptOf(detail) : []), [detail]);
  const hasAudio = detail?.has_audio === true;
  const player = useAudioPlayer(hasAudio && id ? { uri: audioUrlOf(id) } : null);
  const status = useAudioPlayerStatus(player);

  const activeTurn = useMemo(() => {
    if (!status.isLoaded || turns.length === 0) return null;
    let index: number | null = null;
    for (let i = 0; i < turns.length; i++) {
      if (turns[i].offset_seconds <= status.currentTime) index = i;
      else break;
    }
    return index;
  }, [status.isLoaded, status.currentTime, turns]);

  const shareCertificate = async () => {
    if (!id || sharing) return;
    setSharing(true);
    try {
      const doc = await fetchAttestation(id);
      const { uri } = await Print.printToFileAsync({ html: certificateHtml(doc) });
      await shareAsync(uri, {
        mimeType: "application/pdf",
        dialogTitle: "Share the attestation certificate",
        UTI: "com.adobe.pdf",
      });
    } catch {
      setError("Could not build the certificate for this run.");
    } finally {
      setSharing(false);
    }
  };

  if (error)
    return (
      <Text style={{ fontFamily: fonts.evidence, fontSize: 12, color: colors.contra, padding: 20 }}>
        {error}
      </Text>
    );
  if (!detail)
    return (
      <Text style={{ fontFamily: fonts.evidence, fontSize: 12, color: colors.inkFaint, padding: 20 }}>
        Opening the record...
      </Text>
    );

  const analysis = detail.analysis;

  return (
    <ScrollView style={{ flex: 1, backgroundColor: colors.paper }} contentContainerStyle={{ padding: 20, paddingBottom: 48 }}>
      <Text style={{ fontFamily: fonts.displayBold, fontSize: 26, color: colors.ink }}>
        {analysis?.org ?? "Verification run"}
      </Text>
      <Text style={{ fontFamily: fonts.evidence, fontSize: 11, color: colors.inkFaint, marginTop: 4 }}>
        {detail.run_id} · {detail.state}
        {analysis?.replay ? " · replay of a real recorded call" : ""}
      </Text>

      {analysis && (
        <View style={{ marginTop: 14, flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
          <VerdictStamp
            verdict={analysis.reconciliation.verdict}
            probability={analysis.reconciliation.posterior_probability}
          />
          {detail.state === "completed" && (
            <Pressable
              onPress={shareCertificate}
              style={{
                backgroundColor: colors.ink,
                borderRadius: 8,
                paddingHorizontal: 14,
                paddingVertical: 10,
              }}
            >
              <Text style={{ fontFamily: fonts.evidence, fontSize: 11, color: colors.paper, textTransform: "uppercase", letterSpacing: 1 }}>
                {sharing ? "preparing..." : "share certificate"}
              </Text>
            </Pressable>
          )}
        </View>
      )}

      {analysis?.claims.map((claim) => (
        <View
          key={claim.claim}
          style={{
            marginTop: 12,
            padding: 14,
            borderRadius: 10,
            borderWidth: 1,
            borderColor: colors.rule,
            backgroundColor: colors.white,
          }}
        >
          <Text style={{ fontFamily: fonts.evidence, fontSize: 10, textTransform: "uppercase", letterSpacing: 2, color: colors.inkFaint }}>
            {claim.claim.replaceAll("_", " ")}
          </Text>
          <Text
            style={{
              fontFamily: fonts.displayBold,
              fontSize: 24,
              marginTop: 2,
              color: claim.abstain ? colors.inkSoft : claim.answer === "yes" ? colors.trust : colors.doubt,
            }}
          >
            {claim.abstain ? "abstain" : claim.answer}
          </Text>
          <Text style={{ fontFamily: fonts.evidence, fontSize: 11, color: colors.inkSoft, marginTop: 4 }}>
            {claim.span
              ? `evidence: "${claim.span.text}"`
              : "no supporting span: the call did not establish this, so no answer is given"}
          </Text>
        </View>
      ))}

      {hasAudio && (
        <View style={{ marginTop: 16, padding: 14, borderRadius: 10, borderWidth: 1, borderColor: colors.rule, backgroundColor: colors.white }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
            <Pressable
              onPress={() => (status.playing ? player.pause() : player.play())}
              style={{
                width: 44,
                height: 44,
                borderRadius: 22,
                borderWidth: 1,
                borderColor: colors.rule,
                alignItems: "center",
                justifyContent: "center",
                backgroundColor: colors.paper,
              }}
            >
              <Text style={{ fontSize: 16, color: colors.ink }}>
                {status.playing ? "❚❚" : "▶"}
              </Text>
            </Pressable>
            <View style={{ flex: 1 }}>
              <View style={{ height: 4, borderRadius: 2, backgroundColor: colors.paperDeep, overflow: "hidden" }}>
                <View
                  style={{
                    height: 4,
                    width: `${status.duration ? Math.min((status.currentTime / status.duration) * 100, 100) : 0}%`,
                    backgroundColor: colors.trust,
                  }}
                />
              </View>
              <Text style={{ fontFamily: fonts.evidence, fontSize: 10, color: colors.inkFaint, marginTop: 6 }}>
                {detail.audio_note ?? "provenance not recorded for this audio"}
              </Text>
            </View>
          </View>
        </View>
      )}

      <Text style={{ fontFamily: fonts.display, fontSize: 18, color: colors.ink, marginTop: 20 }}>
        Transcript, with evidence marked
      </Text>
      {hasAudio && (
        <Text style={{ fontFamily: fonts.evidence, fontSize: 10, color: colors.inkFaint, marginTop: 2 }}>
          tap a turn to hear it
        </Text>
      )}
      <View style={{ marginTop: 8 }}>
        {turns.map((turn, index) => {
          const marking = analysis?.claims.find((c) => c.span?.turn === index);
          return (
            <Pressable
              key={index}
              disabled={!hasAudio}
              onPress={() => {
                player.seekTo(turn.offset_seconds);
                if (!status.playing) player.play();
              }}
              style={{
                flexDirection: "row",
                gap: 10,
                paddingVertical: 7,
                paddingHorizontal: 6,
                borderBottomWidth: 1,
                borderBottomColor: colors.rule,
                backgroundColor: activeTurn === index ? colors.trustSoft : "transparent",
                borderRadius: 4,
              }}
            >
              <Text style={{ fontFamily: fonts.evidence, fontSize: 10, color: colors.inkFaint, width: 34, textAlign: "right" }}>
                {Math.floor(turn.offset_seconds / 60)}:{String(Math.floor(turn.offset_seconds % 60)).padStart(2, "0")}
              </Text>
              <Text
                style={{
                  fontFamily: fonts.evidence,
                  fontSize: 10,
                  width: 34,
                  textTransform: "uppercase",
                  color: turn.speaker === "bot" ? colors.inkFaint : colors.trust,
                }}
              >
                {turn.speaker}
              </Text>
              <Text style={{ flex: 1, fontFamily: fonts.body, fontSize: 14, color: turn.speaker === "bot" ? colors.inkSoft : colors.ink }}>
                {marking?.span ? (
                  <>
                    {turn.text.slice(0, marking.span.char_start)}
                    <Text style={{ backgroundColor: colors.trustSoft, fontFamily: fonts.bodySemi, color: colors.ink }}>
                      {turn.text.slice(marking.span.char_start, marking.span.char_end)}
                    </Text>
                    {turn.text.slice(marking.span.char_end)}
                  </>
                ) : (
                  turn.text
                )}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {detail.payload?.evidence && (
        <View style={{ marginTop: 20 }}>
          <Text style={{ fontFamily: fonts.display, fontSize: 18, color: colors.ink }}>
            What the caller itself reported
          </Text>
          {detail.payload.evidence.map((line) => (
            <Text key={line} style={{ fontFamily: fonts.body, fontSize: 14, color: colors.inkSoft, marginTop: 6 }}>
              · {line}
            </Text>
          ))}
        </View>
      )}
    </ScrollView>
  );
}
