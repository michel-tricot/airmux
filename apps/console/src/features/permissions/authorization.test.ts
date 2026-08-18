import { describe, expect, it } from 'vitest';
import { operationAuthority, type Permission } from '@workspace/api-client-react';
import { allows, anyOf } from './authorization';

const permissions = (...values: Permission[]) => values;

describe('authorization policies', () => {
  it('allows any permission accepted by an operation check', () => {
    expect(allows(permissions('organizations.read'), operationAuthority.listWorkspaces)).toBe(true);
    expect(allows(permissions('workspaces.read'), operationAuthority.listWorkspaces)).toBe(true);
    expect(allows([], operationAuthority.listWorkspaces)).toBe(false);
  });

  it('requires every check attached to a policy', () => {
    const policy = {
      checks: [
        { scope: 'org_scope', anyOf: permissions('members.read') },
        { scope: 'org_scope', anyOf: permissions('audit.read') },
      ],
    };

    expect(allows(permissions('members.read', 'audit.read'), policy)).toBe(true);
    expect(allows(permissions('members.read'), policy)).toBe(false);
  });

  it('composes alternate operations without repeating their permission names', () => {
    const policy = anyOf(operationAuthority.listOrgAccessKeys, operationAuthority.listBundles, operationAuthority.listOrgUsers);

    expect(allows(permissions('bundles.read'), policy)).toBe(true);
    expect(allows(permissions('audit.read'), policy)).toBe(false);
  });
});
