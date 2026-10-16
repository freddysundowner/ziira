import { api, type Schemas, unwrap, useQuery, useTranslation } from "@/sdk";

type Plain = Schemas["PlainOut"];

/** The plain words for checks, topics, facts and limits, in the language of the screen (loaded once, kept for an hour). */
export function usePlain() {
  const { i18n } = useTranslation();
  const lang = i18n.language === "sw" ? "sw" : "en";
  const q = useQuery({
    queryKey: ["intel", "plain", lang], staleTime: 3_600_000,
    queryFn: () => unwrap(api.GET("/api/v1/intel/plain", { params: { query: { lang } } })),
  });
  const data: Plain | undefined = q.data;
  return {
    data, lang, loading: q.isLoading, error: q.error,
    /** The plain text of a check; an unknown code reads as nothing special (the finding's own words are shown). */
    check: (code: string | null | undefined) => (code ? data?.checks[code] : undefined),
    topicTitle: (key: string) => data?.topics.find((t) => t.key === key)?.title ?? key,
  };
}
