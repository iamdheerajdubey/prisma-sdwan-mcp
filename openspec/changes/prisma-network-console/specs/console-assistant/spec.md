## ADDED Requirements

### Requirement: The assistant is a model with tools, not a keyword router

The question box SHALL answer by giving a model the MCP tool set and letting it select and invoke tools, and SHALL NOT map the question to a tool by matching words against a fixed vocabulary or infer tool arguments from parameter names.

The tools already carry operational descriptions written to be read by a model. Re-deriving intent from keyword lists discards that and fails silently on ordinary phrasing.

#### Scenario: Phrasing does not decide capability

- **WHEN** two differently worded questions ask for the same thing
- **THEN** both are answered from the same underlying tools
- **AND** neither fails because a particular word was absent

#### Scenario: Arguments come from the schema and the question

- **WHEN** the model calls a tool
- **THEN** the arguments are the model's, formed against the tool's declared input schema
- **AND** no argument is filled by matching a parameter's name to a stock value

#### Scenario: An unanswerable question says why

- **WHEN** no available tool can answer the question
- **THEN** the response says what could not be determined and what is available
- **AND** it is distinguishable from a tool that ran and found nothing

#### Scenario: There is no fixed intent vocabulary

- **WHEN** the assistant path is inspected
- **THEN** it contains no enumerated keyword-to-capability mapping used for routing

### Requirement: The assistant can only do what the tools allow

The assistant SHALL be able to invoke only tools exposed by the MCP session, SHALL NOT construct controller or device requests by any other path, and SHALL be bounded in how many calls it may make to answer one question.

#### Scenario: The tool set is the boundary

- **WHEN** the assistant runs
- **THEN** every external effect it produces is an invocation of an exposed tool
- **AND** it has no path to the controller API or a device outside that set

#### Scenario: A runaway loop is bounded

- **WHEN** the model keeps calling tools without concluding
- **THEN** the loop stops at a configured ceiling
- **AND** the partial work is returned, labeled as incomplete rather than presented as an answer

#### Scenario: Active diagnostics are identified before they run

- **WHEN** the assistant is about to invoke a tool that sends real packets from a device
- **THEN** that is surfaced to the user rather than executed indistinguishably from a read
- **AND** the tool's own non-read-only annotation is what identifies it

### Requirement: Credentials are held in memory and fail closed

The console SHALL accept the model API key from the user at runtime, SHALL hold it only in the running process, and SHALL NOT write it to disk, log it, or return it from any endpoint. An environment-supplied key SHALL be accepted as a fallback.

With no key available, the question box SHALL be disabled with an explicit message, and every other part of the console SHALL continue to work.

#### Scenario: The key never persists

- **WHEN** a key is supplied and used
- **THEN** it is not written to any file, log, or response body
- **AND** restarting the console requires supplying it again

#### Scenario: No key disables only the assistant

- **WHEN** no key is available from the user or the environment
- **THEN** the question box reports that it is unavailable and what to supply
- **AND** browsing, inspection, the tool explorer, and preview mode all still work

#### Scenario: The key is never echoed

- **WHEN** any endpoint reports configuration or status
- **THEN** it may report whether a key is present
- **AND** it never returns the value, in whole or in part

#### Scenario: Device credentials are not the model's to see

- **WHEN** the assistant invokes a tool that connects to a device
- **THEN** the device credentials come from the server's own configuration
- **AND** they are neither supplied by nor visible to the model

### Requirement: The user knows what leaves the console

The console SHALL disclose, before the first question is sent, that questions and the tool results gathered to answer them are sent to a third-party model provider.

Tenant topology, device state, and CLI output are the substance of what this tool retrieves. Sending them onward is a decision the operator makes knowingly or not at all.

#### Scenario: Disclosure precedes the first send

- **WHEN** the user is about to use the question box for the first time in a session
- **THEN** the console states that question text and retrieved tool results are sent to the model provider
- **AND** the statement is shown before anything is sent, not after

#### Scenario: Declining leaves the rest usable

- **WHEN** the user does not proceed
- **THEN** nothing is sent
- **AND** the rest of the console remains fully usable

### Requirement: Answers are traceable to the calls behind them

The assistant SHALL present, alongside its answer, the tools it called and the arguments it used, so a claim can be checked against the call that produced it.

#### Scenario: The call chain accompanies the answer

- **WHEN** the assistant answers a question
- **THEN** the tools invoked, in order, with their arguments, are available with the answer
- **AND** each maps to a trace record

#### Scenario: A failed call is visible in the chain

- **WHEN** a tool call fails during the loop
- **THEN** the failure appears in the chain with its error
- **AND** it is not silently omitted from an otherwise confident answer

#### Scenario: An answer with no calls says so

- **WHEN** the assistant answers without invoking any tool
- **THEN** that is stated
- **AND** the answer is not presented as grounded in retrieved data

### Requirement: Model failures are reported as themselves

The console SHALL distinguish a model-provider failure from a tool failure and from an empty result, and SHALL report a declined request as a decline rather than as an error or an empty answer.

#### Scenario: A declined request is named

- **WHEN** the model provider declines to answer
- **THEN** the console reports that the request was declined
- **AND** it is distinguishable from a failed tool call and from a successful empty result

#### Scenario: Authentication failure points at the key

- **WHEN** the supplied key is rejected
- **THEN** the console says the key was rejected and how to replace it
- **AND** the key value does not appear in the message

#### Scenario: Rate limiting is not a wrong answer

- **WHEN** the provider rate-limits or is unavailable
- **THEN** the console reports the condition
- **AND** it does not return a partial or fabricated answer in its place
