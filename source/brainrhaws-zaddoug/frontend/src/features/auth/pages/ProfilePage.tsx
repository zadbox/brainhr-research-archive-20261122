import { useRef, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { AccountProfile } from '../components/AccountProfile';
import { Navigate, useLocation } from 'react-router-dom';

export function ProfilePage() {
  const { user, logout } = useAuth();
  const location = useLocation();
  const inFlight = useRef(false);
  const [signingOut, setSigningOut] = useState(false);
  const [signOutFailed, setSignOutFailed] = useState(false);

  const signOut = async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setSigningOut(true);
    setSignOutFailed(false);
    try {
      await logout();
    } catch {
      setSignOutFailed(true);
    } finally {
      inFlight.current = false;
      setSigningOut(false);
    }
  };

  if (!user) return null;
  if (new URLSearchParams(location.search).has('google')) {
    return <Navigate to={{ pathname: '/account/sign-in', search: location.search }} replace />;
  }
  return <AccountProfile email={user.email} displayName={user.display_name} signingOut={signingOut} signOutFailed={signOutFailed}
    showSignInMethods={user.google_auth_enabled === true}
    onSignOut={() => { void signOut(); }} />;
}
