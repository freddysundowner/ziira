import type { FieldKey, Values } from "./state";

/** What a step needs from the wizard: the answers, a way to change them, and the words for what is wrong. */
export interface FormApi {
  values: Values;
  set: <K extends FieldKey>(key: K, value: Values[K]) => void;
  /** The field was left: show what is wrong with it from now on. */
  blur: (key: FieldKey) => void;
  /** The message to show under a field (empty until the person has touched it), or null. */
  error: (key: FieldKey) => string | null;
}
