/**
 * Runtime module registry: the active modules for this session, and <Slot>, the screen socket.
 */
import { createContext, lazy, type ReactNode, Suspense, useContext, useMemo } from "react";

import type { ModuleDefinition, SlotProps } from "./module";
import { type Access, activeModules, type ActiveContribution, slotContributions } from "./registry";
import { useNavFlags } from "./navFlags";
import { useSession } from "./session";

const ModulesContext = createContext<readonly ModuleDefinition[]>([]);

/** Makes the active modules (enabled units only) available to the app. */
export function ModulesProvider({ all, children }: { all: readonly ModuleDefinition[]; children: ReactNode }) {
  const { enabledUnits } = useSession();
  const active = useMemo(() => activeModules(all, enabledUnits), [all, enabledUnits]);
  return <ModulesContext.Provider value={active}>{children}</ModulesContext.Provider>;
}

export function useActiveModules(): readonly ModuleDefinition[] {
  return useContext(ModulesContext);
}

export function useAccess(): Access {
  const { enabledUnits, can } = useSession();
  const flags = useNavFlags();
  return useMemo(() => ({ enabledUnits, can, flags }), [enabledUnits, can, flags]);
}

/** Contributions to a slot that this user may see, from active modules only. */
export function useSlot(name: string): ActiveContribution[] {
  const modules = useActiveModules();
  const access = useAccess();
  return useMemo(() => slotContributions(modules, name, access), [modules, name, access]);
}

const lazyCache = new Map<ActiveContribution["component"], ReturnType<typeof lazy<React.ComponentType<SlotProps>>>>();

/** Renders one slot contribution (loaded on first use). Use it when a page lays out contributions itself, e.g. as tabs. */
export function SlotContent({ contribution, props = {} }: { contribution: ActiveContribution; props?: SlotProps }) {
  let Component = lazyCache.get(contribution.component);
  if (!Component) {
    Component = lazy(contribution.component);
    lazyCache.set(contribution.component, Component);
  }
  return (
    <Suspense fallback={null}>
      <Component {...props} />
    </Suspense>
  );
}

/**
 * A screen socket. The owner of a page writes <Slot name="products.product.tabs" props={{ productId }} />;
 * any active module that contributes to that slot appears there. With no contributions it renders
 * nothing (or `empty`). Use `render` to wrap each contribution (e.g. as a tab or a card).
 */
export function Slot({
  name,
  props = {},
  render,
  empty = null,
}: {
  name: string;
  props?: SlotProps;
  render?: (contribution: ActiveContribution, content: ReactNode) => ReactNode;
  empty?: ReactNode;
}) {
  const contributions = useSlot(name);
  if (contributions.length === 0) return <>{empty}</>;
  return (
    <>
      {contributions.map((c, i) => {
        const content = <SlotContent contribution={c} props={props} />;
        return <div key={`${c.unit}-${i}`}>{render ? render(c, content) : content}</div>;
      })}
    </>
  );
}

