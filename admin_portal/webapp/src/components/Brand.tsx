// Header lockup. Thin wrapper so header and splash share ONE source of
// truth for the mark (see LogoLockup.tsx). Kept as a named file because four
// pages already import it.

import LogoLockup from "./LogoLockup";

export default function Brand({ href = "/" }: { href?: string }) {
  return <LogoLockup href={href} />;
}
