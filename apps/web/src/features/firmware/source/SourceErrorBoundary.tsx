import { Component, type ReactNode } from "react";

type Props = { fallback: ReactNode; children: ReactNode };
type State = { failed: boolean };

/**
 * Shows FALLBACK, the plain text saying highlighting couldn't load, when the highlighter's chunk
 * fails: a tab left open across a deploy asks for a chunk the server no longer has (decision 5).
 * Anything the highlighter throws lands here too, so the text is never lost to it.
 */
export class SourceErrorBoundary extends Component<Props, State> {
  override state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  override render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}
