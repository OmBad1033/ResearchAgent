import { useState } from 'react';
import { GraphView } from './GraphView';
import { RunParamsForm } from './components/RunParamsForm';
import type { RunParams } from './types';

const RUN_ID = 'demo';

function App() {
  const [params, setParams] = useState<RunParams | null>(null);

  if (!params) {
    return <RunParamsForm onSubmit={setParams} />;
  }
  return (
    <GraphView
      runId={RUN_ID}
      params={params}
      onNewRun={() => setParams(null)}
    />
  );
}

export default App;
