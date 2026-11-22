import { useEffect, useState } from 'react';

/** Share the shell breakpoint so the client picker mounts in only one place. */
export function useMobileNavigation() {
  const [mobile, setMobile] = useState(() => window.matchMedia('(max-width: 1023px)').matches);

  useEffect(() => {
    const query = window.matchMedia('(max-width: 1023px)');
    const update = () => setMobile(query.matches);
    update();
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);

  return mobile;
}
