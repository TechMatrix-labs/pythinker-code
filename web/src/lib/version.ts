declare const __PYTHINKER_CLI_VERSION__: string | undefined;

export const pythinkerCliVersion =
  typeof __PYTHINKER_CLI_VERSION__ !== "undefined" && __PYTHINKER_CLI_VERSION__
    ? __PYTHINKER_CLI_VERSION__
    : "dev";
