import { Text, View } from "react-native";
import { fonts, verdictTone } from "../lib/theme";

/* The notary stamp, native: same rotated-seal language as the web console. */
export default function VerdictStamp({
  verdict,
  probability,
}: {
  verdict: string;
  probability: number;
}) {
  const tone = verdictTone(verdict);
  return (
    <View
      style={{
        borderWidth: 2,
        borderColor: tone.color,
        backgroundColor: tone.soft,
        borderRadius: 8,
        paddingHorizontal: 14,
        paddingVertical: 8,
        transform: [{ rotate: "-3deg" }],
        alignSelf: "flex-start",
      }}
    >
      <Text
        style={{
          fontFamily: fonts.evidenceMedium,
          fontSize: 14,
          letterSpacing: 2,
          textTransform: "uppercase",
          color: tone.color,
        }}
      >
        {verdict}
      </Text>
      <Text
        style={{
          fontFamily: fonts.evidence,
          fontSize: 10,
          color: tone.color,
          marginTop: 2,
        }}
      >
        posterior {Math.round(probability * 100)}%
      </Text>
    </View>
  );
}
