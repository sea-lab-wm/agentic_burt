import { FormEvent } from "react";

type ComposerProps = {
  disabled: boolean;
  draft: string;
  onDraftChange: (value: string) => void;
  onSubmit: () => void;
};

export function Composer({
  disabled,
  draft,
  onDraftChange,
  onSubmit,
}: ComposerProps) {
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit();
  }

  return (
    <form className="composer" onSubmit={handleSubmit}>
      <textarea
        aria-label="Message BURT"
        className="composer__input"
        disabled={disabled}
        placeholder="Describe the bug, answer a follow-up question, or add more detail."
        rows={1}
        value={draft}
        onChange={(event) => onDraftChange(event.target.value)}
      />
      <button
        className="composer__submit"
        disabled={disabled || draft.trim().length === 0}
        type="submit"
      >
        Send
      </button>
    </form>
  );
}
