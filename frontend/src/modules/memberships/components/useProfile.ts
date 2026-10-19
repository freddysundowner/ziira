import { ApiError, api, unwrap, useQuery } from "@/sdk";

import type { Profile } from "../hooks";

/** The gym profile of a customer, or null when they have none yet (a customer who never joined or visited). */
export function useProfile(customerId: string) {
  return useQuery({
    enabled: !!customerId, queryKey: ["memberships", "profile", customerId], retry: false,
    queryFn: async (): Promise<Profile | null> => {
      try {
        return await unwrap(api.GET("/api/v1/memberships/profiles/by-customer/{customer_id}", { params: { path: { customer_id: customerId } } }));
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null;
        throw e;
      }
    },
  });
}

/** The pictures attached to a profile (the list the Photos component also uses, so both stay in step) and the address of the main one. */
export function useProfilePhotos(profile: Profile | null | undefined) {
  const q = useQuery({
    enabled: !!profile, retry: false, staleTime: 60_000, refetchInterval: 4 * 60_000,
    queryKey: ["attachments", "memberships.profile", profile?.id ?? ""],
    queryFn: () => unwrap(api.GET("/api/v1/files", { params: { query: { entity_type: "memberships.profile", entity_id: profile?.id ?? "" } } })),
  });
  const main = q.data?.find((f) => f.id === profile?.photo_file_id);
  return { files: q.data ?? [], mainUrl: main?.thumb_url ?? null };
}
