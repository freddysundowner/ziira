import { useQuery } from "@tanstack/react-query";

import { Alert, Skeleton, useDebounced, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";

const STYLE = `<style>:root{color-scheme:light dark}body{font:15px/1.6 system-ui,sans-serif;margin:0;padding:12px;overflow-wrap:anywhere}
h1,h2,h3{line-height:1.25}h1{font-size:1.5em}h2{font-size:1.25em}img{max-width:100%}table{border-collapse:collapse}td,th{border:1px solid #8884;padding:4px 8px}
blockquote{margin-left:0;padding-left:12px;border-left:3px solid #8886}code,pre{background:#8882;padding:2px 4px;border-radius:4px}</style>`;

/**
 * The server's safe HTML for a Markdown text, shown inside a sandboxed frame (no scripts, no forms, no navigation), so
 * even a flaw in the server's cleaning could not run anything in the console. Pictures from the library show their
 * description until the page is published.
 */
export function SafePreview({ markdown, title }: { markdown: string; title?: string }) {
  const { t } = useTranslation("operator");
  const text = useDebounced(markdown, 400);
  const html = useQuery({
    queryKey: ["operator", "site", "preview", text],
    queryFn: () => opUnwrap(opApi.POST("/api/v1/operator/site/preview", { body: { markdown: text } })),
    staleTime: Infinity,
    placeholderData: (previous) => previous,
  });
  if (html.isError) return <Alert tone="bad">{html.error.message}</Alert>;
  if (!html.data) return <Skeleton className="h-40 w-full" />;
  return (
    <iframe title={title ?? t("website.pages.preview")} sandbox="" referrerPolicy="no-referrer"
      srcDoc={`<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">${STYLE}${html.data.html}`}
      className="h-[28rem] w-full rounded-lg border border-line bg-surface" />
  );
}
