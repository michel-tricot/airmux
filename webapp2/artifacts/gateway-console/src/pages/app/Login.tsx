import { useListUsers } from '@workspace/api-client-react';
import { useSession } from '@/lib/session';
import { Card, Button } from '@/components/ui/elements';
import { TerminalSquare, UserCircle } from 'lucide-react';

export default function AppLogin() {
  const { data: users, isLoading } = useListUsers();
  const { setUserId } = useSession();

  return (
    <div className="min-h-[100dvh] flex items-center justify-center bg-muted/30 p-4">
      <Card className="w-full max-w-md p-8 shadow-xl border-border/50">
        <div className="flex flex-col items-center mb-8">
          <div className="w-12 h-12 rounded bg-primary text-primary-foreground flex items-center justify-center mb-4">
            <TerminalSquare className="w-6 h-6" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight">Sign in to Gateway</h1>
          <p className="text-muted-foreground text-sm mt-1">Select a user to simulate authentication.</p>
        </div>
        
        {isLoading ? (
          <div className="text-center text-sm font-mono text-muted-foreground">Loading users...</div>
        ) : (
          <div className="space-y-2">
            {users?.map(user => (
              <Button 
                key={user.id} 
                variant="outline" 
                className="w-full justify-start h-12 text-left hover:border-primary hover:bg-primary/5 group"
                onClick={() => setUserId(user.id)}
              >
                <UserCircle className="w-5 h-5 mr-3 text-muted-foreground group-hover:text-primary transition-colors" />
                <span className="flex-1 font-medium">{user.name}</span>
                <span className="text-xs text-muted-foreground font-mono">{user.email}</span>
              </Button>
            ))}
            {users?.length === 0 && (
              <div className="text-center p-4 border border-dashed rounded-md text-muted-foreground text-sm">
                No users configured in the system.
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
