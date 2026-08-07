import { FormEvent, useLayoutEffect, useRef } from "react";

type ComposerProps = {
  disabled: boolean;
  draft: string;
  onDraftChange: (value: string) => void;
  onSubmit: () => void;
};

const MAX_HEIGHT_RATIO = 0.4;

export function Composer({
  disabled,
  draft,
  onDraftChange,
  onSubmit,
}: ComposerProps) {
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  useLayoutEffect(() => {
    function fitInputToContent(): void {
      const input = inputRef.current;
      if (!input) {
        return;
      }

      const maxHeight = window.innerHeight * MAX_HEIGHT_RATIO;
      input.style.height = "auto";
      input.style.height = `${Math.min(input.scrollHeight, maxHeight)}px`;
      input.style.overflowY = input.scrollHeight > maxHeight ? "auto" : "hidden";
    }

    fitInputToContent();
    window.addEventListener("resize", fitInputToContent);

    return () => {
      window.removeEventListener("resize", fitInputToContent);
    };
  }, [draft]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit();
  }

  return (
    <form className="composer" onSubmit={handleSubmit}>
      <textarea
        ref={inputRef}
        aria-label="Message BURT"
        className="composer__input"
        disabled={disabled}
        placeholder="Describe the bug, answer a follow-up question, or add more detail."
        rows={1}
        value={draft}
        onChange={(event) => onDraftChange(event.target.value)}
      />
      <button
        aria-label="Send"
        className="composer__submit"
        disabled={disabled || draft.trim().length === 0}
        title="Send"
        type="submit"
      >
        <svg
          aria-hidden="true"
          focusable="false"
          height="20"
          viewBox="0 0 24 24"
          width="20"
        >
          <path d="M2.01 21 23 12 2.01 3 2 10l15 2-15 2z" fill="currentColor" />
        </svg>
      </button>
    </form>
  );
}
