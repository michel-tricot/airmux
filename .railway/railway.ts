import { defineRailway, github, postgres, project, service, volume } from 'railway/iac';

export default defineRailway(() => {
  const database = postgres('postgres');
  const state = volume('airllm-state', { region: 'iad', sizeMB: 500 });
  const airllm = service('airllm', {
    source: github('michel-tricot/airllm', { branch: 'main' }),
    healthcheck: '/healthz',
    healthcheckTimeout: 30,
    replicas: 1,
    env: {
      AIRLLM_CONSOLE_URL: 'https://${{RAILWAY_PUBLIC_DOMAIN}}',
      DATABASE_URL: database.env.DATABASE_URL,
      PORT: '8080',
    },
    volumeMounts: {
      '/state': state,
    },
  });

  return project('airllm', { resources: [airllm, database, state] });
});
