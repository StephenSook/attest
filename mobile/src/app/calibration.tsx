import { useEffect, useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { fetchMetrics, type Metrics } from "../lib/api";
import { colors, fonts } from "../lib/theme";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <View
      style={{
        flex: 1,
        minWidth: 100,
        padding: 12,
        borderRadius: 10,
        borderWidth: 1,
        borderColor: colors.rule,
        backgroundColor: colors.white,
      }}
    >
      <Text style={{ fontFamily: fonts.evidence, fontSize: 9, textTransform: "uppercase", letterSpacing: 1.5, color: colors.inkFaint }}>
        {label}
      </Text>
      <Text style={{ fontFamily: fonts.displayBold, fontSize: 22, color: colors.ink, marginTop: 2 }}>
        {value}
      </Text>
    </View>
  );
}

/* Every number on this screen is served live from the same metrics the web
   console uses; nothing is baked into the app. */
export default function CalibrationScreen() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchMetrics()
      .then(setMetrics)
      .catch(() => setError("Could not load metrics; the backend may be waking up."));
  }, []);

  if (error)
    return <Text style={{ fontFamily: fonts.evidence, fontSize: 12, color: colors.doubt, padding: 20 }}>{error}</Text>;
  if (!metrics)
    return <Text style={{ fontFamily: fonts.evidence, fontSize: 12, color: colors.inkFaint, padding: 20 }}>Loading the evidence...</Text>;

  const head = metrics.headline;
  const real = metrics.real_channel;

  return (
    <ScrollView style={{ flex: 1, backgroundColor: colors.paper }} contentContainerStyle={{ padding: 20, paddingBottom: 48 }}>
      <Text style={{ fontFamily: fonts.body, fontSize: 15, color: colors.inkSoft }}>
        Attest answers only when a calibrated prediction set contains exactly
        one value; otherwise it abstains. Measured on held-out data, seed{" "}
        {metrics.seed}.
      </Text>

      <View style={{ flexDirection: "row", gap: 10, marginTop: 16, flexWrap: "wrap" }}>
        <Stat
          label={`coverage at ${Math.round(head.target_coverage * 100)}% target`}
          value={`${(head.empirical_coverage * 100).toFixed(1)}%`}
        />
        <Stat label="abstention" value={`${(head.abstention_rate * 100).toFixed(1)}%`} />
        <Stat
          label="accuracy when answering"
          value={`${(head.accuracy_when_answering * 100).toFixed(1)}%`}
        />
      </View>

      {real && (
        <View
          style={{
            marginTop: 20,
            padding: 16,
            borderRadius: 10,
            borderWidth: 2,
            borderColor: colors.trust,
            backgroundColor: colors.white,
          }}
        >
          <Text style={{ fontFamily: fonts.display, fontSize: 18, color: colors.ink }}>
            Tested on the real telephone
          </Text>
          <Text style={{ fontFamily: fonts.evidence, fontSize: 11, color: colors.inkSoft, marginTop: 6 }}>
            {real.n_collected} real calls to a consented line, pre-registered
            scripted ground truth, scored with the harness-calibrated
            threshold. {real.n_excluded_by_protocol} excluded by the documented
            deviation protocol; the worst-case floor counting every excluded
            call as a miss is{" "}
            {((real.worst_case_coverage_all_excluded_as_misses ?? 0) * 100).toFixed(1)}
            %.
          </Text>
          <View style={{ flexDirection: "row", gap: 10, marginTop: 12, flexWrap: "wrap" }}>
            <Stat
              label={`real coverage (n=${real.n_collected})`}
              value={`${(real.empirical_coverage * 100).toFixed(1)}%`}
            />
            <Stat
              label="Wilson lower bound"
              value={`${(real.coverage_wilson_95[0] * 100).toFixed(1)}%`}
            />
          </View>
        </View>
      )}

      {metrics.mondrian && (
        <View style={{ marginTop: 20 }}>
          <Text style={{ fontFamily: fonts.display, fontSize: 18, color: colors.ink }}>
            The average was hiding a class
          </Text>
          {metrics.mondrian.per_class.map((row) => (
            <View
              key={row.label}
              style={{
                flexDirection: "row",
                justifyContent: "space-between",
                paddingVertical: 8,
                borderBottomWidth: 1,
                borderBottomColor: colors.rule,
              }}
            >
              <Text style={{ fontFamily: fonts.evidence, fontSize: 12, color: colors.ink }}>
                {row.label} (n={row.n})
              </Text>
              <Text
                style={{
                  fontFamily: fonts.evidence,
                  fontSize: 12,
                  color:
                    row.marginal_coverage < 1 - (metrics.mondrian?.alpha ?? 0.1)
                      ? colors.doubt
                      : colors.inkSoft,
                }}
              >
                {(row.marginal_coverage * 100).toFixed(1)}% →{" "}
                {(row.mondrian_coverage * 100).toFixed(1)}%
              </Text>
            </View>
          ))}
          <Text style={{ fontFamily: fonts.evidence, fontSize: 10, color: colors.inkFaint, marginTop: 8 }}>
            marginal coverage → class-conditional coverage, held-out fold
          </Text>
        </View>
      )}
    </ScrollView>
  );
}
