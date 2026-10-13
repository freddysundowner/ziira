/**
 * Every frontend module built into the app. The shell activates each one only when the business
 * has its backend unit enabled. Adding a module: create src/modules/<unit>/module.ts and list it here.
 */
import type { ModuleDefinition } from "@/sdk";

import admin from "./admin/module";
import catalogStats from "./catalog_stats/module";
import products from "./products/module";

export const allModules: readonly ModuleDefinition[] = [admin, products, catalogStats];
