import { allOf } from '@/features/permissions/authorization';
import { providerCredentialAccess } from '@/features/credentials/policy';
import { catalogAccess } from '@/features/catalog/policy';

export const onboardingAccess = allOf(providerCredentialAccess.instance.read, providerCredentialAccess.instance.create, catalogAccess.instance.read);
