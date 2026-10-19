/** The shortest operator password the server accepts (it also refuses common passwords and the email). */
export const MIN_PASSWORD = 8;

export interface PasswordForm {
  current: string;
  next: string;
  repeat: string;
}

/** What is wrong with the form so far, as a translation key (null when it can be sent). Empty fields are not yet a problem. */
export function passwordProblem(form: PasswordForm): "short" | "same" | "mismatch" | null {
  if (form.next && form.next.length < MIN_PASSWORD) return "short";
  if (form.next && form.current && form.next === form.current) return "same";
  if (form.repeat && form.next !== form.repeat) return "mismatch";
  return null;
}

export const passwordReady = (form: PasswordForm): boolean =>
  form.current.length > 0 && form.next.length >= MIN_PASSWORD && passwordProblem(form) === null && form.repeat === form.next;
