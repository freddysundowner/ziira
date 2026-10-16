import { api, unwrap, type Schemas } from "./api";
import { useQuery } from "@tanstack/react-query";

export type AvailableChannel = Schemas["AvailableChannel"];

/** What a channel setting offers: the channels the business has now, plus the value already stored if it is gone (shown as
 *  "not available" so the person sees it is kept but not used). `extra` are fixed choices such as "off" or "in_app". */
export function channelOptions(available: AvailableChannel[], current: string | undefined, extra: string[] = []): { value: string; label: string; missing: boolean }[] {
  const options = [
    ...extra.map((value) => ({ value, label: value, missing: false })),
    ...available.map((c) => ({ value: c.channel, label: c.label, missing: false })),
  ];
  if (current && !options.some((o) => o.value === current)) options.push({ value: current, label: current, missing: true });
  return options;
}

/** The channels this business can use: only those whose provider (plugin) is switched on for it. Every select of a channel is
 *  built from this list; nothing in the web app names a channel itself except the built-in email and SMS labels. */
export function useChannels(companyId?: string) {
  return useQuery({
    queryKey: ["available-channels", companyId ?? "all"],
    queryFn: () => unwrap(api.GET("/api/v1/notifications/channels/available", { params: { query: companyId ? { company_id: companyId } : {} } })),
    staleTime: 60_000,
  });
}
