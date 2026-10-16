/** Types for the Help centre: step-by-step guides for using Ziira. English only. */

export interface HelpShot {
  /** File name (no extension) in src/assets/help/, made by scripts/capture-help-screens.mjs */
  key: string;
  alt: string;
  /** What each numbered circle on the picture points at, in order (1, 2, 3 ...). */
  legend?: string[];
}

export interface HelpStep {
  /** One action. Inline markup: **bold** for words exactly as they appear on screen, [text](@page-id) for links. */
  do: string;
  /** What you should see afterwards. */
  result?: string;
  shot?: HelpShot;
  /** A short extra remark for this step. */
  note?: string;
}

export interface HelpProblem { p: string; fix: string }

export interface HelpGuide {
  /** URL slug under /help/<journey>/ */
  slug: string;
  journey: string;
  /** <title>, up to 60 characters */
  title: string;
  /** Meta description, 50 to 160 characters */
  description: string;
  /** The goal, phrased the way the user would say it: "Make your first sale" */
  h1: string;
  who: string;
  time: string;
  /** Minutes, for the HowTo structured data (PT#M) */
  minutes: number;
  need: string[];
  intro?: string;
  /** An honest status remark, shown in a note box (for example "not yet tested with a live service") */
  status?: string;
  steps: HelpStep[];
  problems: HelpProblem[];
  tips: string[];
  /** "slug" of another guide, or "@page-id" of a site page */
  next: string[];
  /** Words people may search for that are not in the title */
  keywords?: string[];
  updated?: string;
}

export interface HelpJourney { id: string; n: number; title: string; blurb: string; description: string }
