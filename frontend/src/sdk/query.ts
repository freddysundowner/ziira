import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

/**
 * A list the server pages with limit/offset. Asks for one row more than the page to know whether a next page exists, so
 * the screen never offers an empty page. Changing `key` (a filter or search) goes back to page one.
 */
export function usePagedList<T>(key: readonly unknown[], fetchPage: (limit: number, offset: number) => Promise<T[]>, pageSize = 25) {
  const [pages, setPages] = useState<{ key: string; page: number }>({ key: "", page: 0 });
  const sig = JSON.stringify(key);
  const page = pages.key === sig ? pages.page : 0;
  const query = useQuery({
    queryKey: [...key, "page", page, pageSize],
    queryFn: () => fetchPage(pageSize + 1, page * pageSize),
    placeholderData: keepPreviousData,
  });
  const all = query.data ?? undefined;
  return {
    query,
    rows: all?.slice(0, pageSize),
    page,
    setPage: (p: number) => setPages({ key: sig, page: p }),
    hasNext: (all?.length ?? 0) > pageSize,
  };
}
