/**
 * Every frontend module built into the app. The shell activates each one only when the business
 * has its backend unit enabled. Adding a module: create src/modules/<unit>/module.ts and list it here.
 */
import type { ModuleDefinition } from "@/sdk";

import admin from "./admin/module";
import catalogStats from "./catalog_stats/module";
import command from "./command/module";
import connect from "./connect/module";
import products from "./products/module";
import crm from "./crm/module";
import finance from "./finance/module";
import imports from "./imports/module";
import intel from "./intel/module";
import leadsintel from "./leadsintel/module";
import inventory from "./inventory/module";
import messaging from "./messaging/module";
import people from "./people/module";
import payments from "./payments/module";
import pos from "./pos/module";
import purchasing from "./purchasing/module";

export const allModules: readonly ModuleDefinition[] = [
  admin, products, inventory, pos, crm, payments, purchasing, finance, people, messaging, leadsintel, catalogStats, command, intel, imports, connect,
];
