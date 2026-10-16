import type { HelpGuide } from "./types";
import { getStarted } from "./get-started";
import { sell } from "./sell";
import { stock } from "./stock";
import { buy } from "./buy";
import { customers } from "./customers";
import { money } from "./money";
import { people } from "./people";
import { intelligence } from "./intelligence";
import { settings } from "./settings";
import { support } from "./support";

export const allGuides: HelpGuide[] = [...getStarted, ...sell, ...stock, ...buy, ...customers, ...money, ...people, ...intelligence, ...settings, ...support];
