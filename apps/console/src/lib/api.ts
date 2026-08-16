import { setDefaultHeaders } from '@workspace/api-client-react';

setDefaultHeaders(() => ({ 'X-Requested-With': 'XMLHttpRequest' }));
