import type { UseQueryResult } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { Card, ErrorState, Skeleton } from "@/sdk";

/** A card that reads its own data: a skeleton while loading, an error with retry, then the content. One failing section never blanks the page. */
export function Section<T>({ query, title, description, actions, children, skeleton = "h-40", errorTitle, className }: {
  query: Pick<UseQueryResult<T>, "isPending" | "isError" | "error" | "data" | "refetch">;
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: (data: T) => ReactNode;
  skeleton?: string;
  errorTitle: string;
  className?: string;
}) {
  return (
    <Card title={title} description={description} actions={actions} className={className}>
      {query.isPending ? <Skeleton className={`${skeleton} w-full`} />
        : query.isError ? <ErrorState title={errorTitle} message={query.error?.message} onRetry={() => void query.refetch()} />
          : children(query.data as T)}
    </Card>
  );
}
