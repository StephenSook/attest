import { Link, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import {
  FlatList,
  Pressable,
  RefreshControl,
  Text,
  View,
} from "react-native";
import { fetchRuns, type RunSummary } from "../lib/api";
import { colors, fonts } from "../lib/theme";

/* The runs ledger: every verification this deployment has performed.
   Public data only, phone numbers masked server-side, replays labeled. */
export default function RunsScreen() {
  const router = useRouter();
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await fetchRuns();
      setRuns(data.runs);
      setError(null);
    } catch {
      setError(
        "Could not reach the Attest API. The free-tier backend may be waking up; pull to retry.",
      );
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  return (
    <View style={{ flex: 1, backgroundColor: colors.paper }}>
      <View style={{ paddingHorizontal: 20, paddingTop: 8, paddingBottom: 12 }}>
        <Text style={{ fontFamily: fonts.body, fontSize: 15, color: colors.inkSoft }}>
          The phone agent that refuses to guess. Every run below is a real
          recorded verification, served by the same API as the web console.
        </Text>
        <Link href="/calibration" asChild>
          <Pressable>
            <Text
              style={{
                fontFamily: fonts.evidence,
                fontSize: 12,
                color: colors.trust,
                marginTop: 8,
                textTransform: "uppercase",
                letterSpacing: 1.5,
              }}
            >
              see the guarantee, measured
            </Text>
          </Pressable>
        </Link>
      </View>

      {error && (
        <Text
          style={{
            fontFamily: fonts.evidence,
            fontSize: 12,
            color: colors.doubt,
            paddingHorizontal: 20,
            paddingBottom: 8,
          }}
        >
          {error}
        </Text>
      )}

      <FlatList
        data={runs ?? []}
        keyExtractor={(item) => item.run_id}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} />}
        ListEmptyComponent={
          !error ? (
            <Text
              style={{
                fontFamily: fonts.evidence,
                fontSize: 12,
                color: colors.inkFaint,
                padding: 20,
              }}
            >
              Opening the ledger...
            </Text>
          ) : null
        }
        renderItem={({ item }) => (
          <Pressable
            onPress={() => router.push(`/run/${item.run_id}`)}
            style={({ pressed }) => ({
              marginHorizontal: 16,
              marginVertical: 6,
              padding: 16,
              borderRadius: 10,
              borderWidth: 1,
              borderColor: colors.rule,
              backgroundColor: pressed ? colors.paperDeep : colors.white,
            })}
          >
            <Text style={{ fontFamily: fonts.display, fontSize: 18, color: colors.ink }}>
              {item.org ?? "Verification run"}
            </Text>
            <Text
              style={{
                fontFamily: fonts.evidence,
                fontSize: 11,
                color: colors.inkFaint,
                marginTop: 4,
              }}
            >
              {item.run_id} · {item.state}
              {item.replay ? " · replay of a real recorded call" : ""}
            </Text>
          </Pressable>
        )}
      />
    </View>
  );
}
