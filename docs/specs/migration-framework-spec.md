# Technical Specification: Multi-Agent Hierarchical Modernization & Verification Framework

This specification sheet defines the architectural design, scaling strategies, proprietary integration mechanisms, and verification pipelines for the autonomous migration of legacy COBOL codebases to modern, modular, and behaviorally equivalent Java architectures.

---

## 1. System Architecture & Dual-Agent Core

The framework leverages a cooperative multi-agent and program-analysis hybrid architecture to ingest legacy COBOL artifacts, design modern object-oriented class hierarchies, and translate/verify executable logic.

```
                  +-----------------------------------+
                  |        COBOL Source Code          |
                  +-----------------------------------+
                                    |
                                    v
                  +-----------------------------------+
                  |      Static Program Analysis      |
                  |     (Class & Method Designers)    |
                  +-----------------------------------+
                                    |
                    +---------------+---------------+
                    |                               |
                    v                               v
          +-------------------+           +-------------------+
          |  Class Structure  |           |  Method Skeleton  |
          |     Metadata      |           |     Metadata      |
          +-------------------+           +-------------------+
                    |                               |
                    +---------------+---------------+
                                    |
                                    v
                  +-----------------------------------+
                  |      LLM-Based Translation        |
                  |   (Code Processing Agent - e.g.,  |
                  |     Granite-34B / Granite-20B)    |
                  +-----------------------------------+
                                    |
                                    v
                  +-----------------------------------+
                  |      Text Processing Agent        |
                  |   (Refinement/Polishing - GPT)    |
                  +-----------------------------------+
                                    |
                                    v
                  +-----------------------------------+
                  |     Verification & Repair Loop    |
                  |   (LegacyWeaver & Locksmith Gate) |
                  +-----------------------------------+
```

### 1.1 Core Agents & Task Division
1. **Code Processing Agent**: A specialized LLM fine-tuned on legacy dialects (e.g., `granite-34b-code-instruct` or `granite-20b-code-cobol`) [27, 547]. It parses individual COBOL procedural paragraphs and produces initial, structurally correct modern language equivalents [6, 27].
2. **Text Processing Agent**: A high-capacity, long-context natural language model (e.g., `gpt-4o-mini`) used to refine code translation, merge paragraph-level explanations, eliminate redundancies, and format outputs to comply with standard Java conventions [6, 28].

---

## 2. Dynamic Verification & Targeted Repair (Avoiding Monolithic Runs)

To eliminate the need for end-to-end monolithic mainframe execution for every minor code modification, the framework implements a granular, off-mainframe differential verification harness.

### 2.1 Paragraph-by-Paragraph Translation & Mocking
* **Modular Segmentation**: The system parses the COBOL `PROCEDURE DIVISION` into discrete, logical paragraphs [12]. Reaching-definitions (RD) and control-flow analysis map global COBOL variables into localized parameters and return types [541, 543].
* **Off-Mainframe Instrumented Execution**: The framework executes the original legacy code (compiled via GnuCOBOL) and the target Java classes on commodity offline hardware [359, 378, 597].
* **Dynamic Mocking**: High-level mainframe mechanisms—such as database queries (`EXEC SQL`), transactional platform APIs (`EXEC CICS`), sequential files, and external subprogram calls (`CALL`)—are intercepted and mocked dynamically by a deterministic COBOL/Java Mock Generator [365, 378].

### 2.2 Byte-for-Byte Parity & Autonomous Repair Loop
* **The Parity Gate**: Legacy outputs are captured and verified against Java target execution outcomes across three deterministic axes [392, 393]:
  1. **Paragraphs Hit**: Set-wise equivalence of executed control paths.
  2. **External Stub Log**: Chronologically ordered sequence of external middleware calls and mock interactions.
  3. **Terminal State**: Pointwise byte-level value equivalence of output variables and files.
* **Failure Memory & Self-Debugging**: Verified divergences are processed by a local repair agent [597]. It logs failures into a persistent "Failure Memory" database [598]. During subsequent iterations, the code-generator checks this memory to prune the search space and ensure identical translation bugs are never generated twice [598, 602].
* **Delta Debugging**: When a test fails due to complex inputs, a delta debugging algorithm partitions and minimizes the input to isolate the exact, minimal failure-inducing counterexample [255, 259, 278]. This provides highly focused context for the LLM to patch the candidate code [278, 281].

---

## 3. High-Volume Scaling & Enterprise Program-Analysis Guidance

A major bottleneck of pure LLM modernization is the input token limit and the "lost in the middle" phenomenon when digesting hundreds of thousands of lines of code. The framework bypasses this with a structured, hierarchical approach.

### 3.1 Hierarchical Segmenting & Merging
For massive source code files, the code is recursively split into functional blocks [10, 58]. The Code Processing Agent translates these segments, and the Text Processing Agent iteratively merges the segment-level outputs, utilizing topological call rankings to maintain global context [6, 24, 36].

### 3.2 Metadata-Guided Static Analysis (WCA for Z Blueprint)
Prior to logic translation, compiler-theory analysis engines extract a global "blueprint" of the application, serving as a guiding scaffold for the LLM [513, 524]:
* **Class Designer**: Scans the COBOL `DATA DIVISION` and copybooks to model an application-wide object-oriented representation [513, 525]. It identifies logical entities, handles data normalization, and establishes shared class structures to avoid redundant class generations across modular translations [525, 528, 536].
* **Method Designer**: Restructures unstructured COBOL control flow (such as `GO TO` and `PERFORM THRU`) into reducible control-flow graphs (CFGs) to map paragraphs into clean Java method signatures [513, 525, 540]. It uses variable access frequency to assign methods to their cohesive Java classes [539, 546].

---

## 4. Mainframe-Specific & Proprietary Connector Integrations

Modernizing mainframe enterprise software requires bridging the fundamental semantic gap between static mainframe memory structures and dynamic, object-oriented environments.

### 4.1 Memory Layout Mapping & Serialization
Mainframe systems rely on exact, byte-level memory overlays (defined via the `REDEFINES` construct) [518, 533]. Because Java does not naturally support physical memory reinterpretation, the framework enforces exact compatibility:
* **Byte-Buffer Mirroring**: For each redefined record, the framework generates cohesive subclasses extending a base representation [533].
* **Deterministic Accessors**: Rather than generating naive fields, the Class Designer produces explicit `getBytes()` and `setBytes()` serialization methods [538]. These utilities pack and unpack variables to and from a shared physical `byte[]` buffer based on their exact PIC offsets, signs, and scales, preserving byte-alignment during SQL, CICS, and file transactions [532, 537, 538].
* **Decimal Precision**: Datatypes like packed decimals (`COMP-3`) and fixed-point representations are automatically mapped to Java `BigDecimal` objects rather than floating-point primitive types to prevent financial rounding discrepancies [532].

### 4.2 Legacy Subsystem Substitutions
To operate offline on modern cloud infrastructure, proprietary connectors are mapped to modern, cloud-native equivalents [371]:
* **Data Layer**: Mainframe RDBMS instances are replaced with PostgreSQL [371].
* **Messaging**: MQ Series transactions are substituted with RabbitMQ instances [371].
* **Middleware**: Complex transactional middleware APIs (`EXEC CICS`, `EXEC IMS`) are mapped to RESTful endpoints, with the application state preserved via containerized microservice architectures [106].

---

## 5. Topological Bottom-Up (Leaf-First) Migration & Verification Pipeline

To systematically manage state-space complexity and accelerate debugging, the framework structures the migration as a Directed Acyclic Graph (DAG) executed from the leaves upward.

```
                    [ Root Program (Orchestrator) ]
                                /       \
                               v         v
                     [ Parent A ]       [ Parent B ]
                        /                    \
                       v                      v
                [ Leaf Module 1 ]      [ Leaf Module 2 ]
                 (Zero calls out)       (Zero calls out)
```

### 5.1 DAG Construction & Topological Sorting
The compiler front-end parses the legacy system, scanning `CALL`, `LINK`, `PERFORM`, and `GO TO` commands [24, 378]. 
1. Nodes are defined as paragraph or file modules, and edges as control/data-flow dependencies [24].
2. A Directed Acyclic Graph (DAG) is constructed using topological sorting (e.g., via the NetworkX library) [24, 244].
3. Nodes with an out-degree of 0 (modules that call nothing else) are classified as **Leaf Nodes** [24]. Nodes with an in-degree of 0 are classified as **Root Nodes** [24].

### 5.2 Step-by-Step Bottom-Up Verification Workflow

#### Step 1: Leaf Isolation & Code Translation
The migration engine isolates the leaf nodes first. Because they do not invoke external code, they are highly self-contained. The Code Processing Agent translates these leaf modules into target Java code blocks [127, 382].

#### Step 2: Witness Input Search & Output Caching
The isolated leaf is subjected to an exhaustive **Witness Search** utilizing six parallel search-based testing and fuzzing algorithms to maximize branch coverage [359, 383, 384]:
* **Pairwise Interaction Testing**: Generates small test sets covering every possible pair of variable choices to satisfy compound `IF` conditions [384].
* **Three-Way Interaction Testing**: Exposes complex paths requiring three coordinated inputs (e.g., file-status × record type × EOF flags) [384].
* **Latin Hypercube Sampling**: Bins and samples quasi-continuous variables (e.g., account balances, quantities) to maximize testing distance [384].
* **Adaptive Random Testing**: Biases input generation toward completely unexplored regions of the input space [384].
* **MAP-Elites**: Groups execution profiles into structural "shapes" (e.g., clean EOF, midstream error exits) and retains the best test cases per shape [384].
* **Upper-Confidence-Bound (UCB1) Bandit**: Learns which variable domains trigger new branch coverage, dynamically prioritizing high-yield input spaces [384, 385].

During execution, the original COBOL and migrated Java are run against the generated witness inputs. The resulting outputs, return states, and variables are cached as a deterministic **Mock Map** [379, 385, 396].

#### Step 3: Upstream Propagation & Stubbing
Once the leaves are validated and locked under a strict **Parity Gate**, the framework moves up one topological layer to parent modules:
* **Harness Side-Channel Stubbing**: When parent modules are compiled and tested, their down-calls to the previously verified leaf nodes are intercepted. 
* **State Substitution**: Instead of executing the child code again, the test harness feeds the parent the cached, deterministic outputs from the leaf's Mock Map.
* **Simplification**: This eliminates state-space explosion, reduces the testing search space, and guarantees that any discovered bugs are strictly localized to the parent module currently under translation [373, 390].

### 5.3 Technical Benefits of the Leaf-First Approach
1. **Defeats Combinatorial Explosion**: Testing a root-level transaction end-to-end requires traversing billions of path possibilities. Bottom-up mocking isolates complexity to manageable, unit-level sweeps [373].
2. **Precise Bug Localization**: When a behavioral divergence is flagged by the Parity Gate, the system knows with 100% certainty that the bug resides in the parent module currently being migrated, since all downstream dependencies are stubbed with pre-verified values [390].
3. **Optimized Variable Scoping**: By tracing the data flow upward through the DAG, the system identifies how variables are read and mutated across child boundaries. This information is used to design clean Java method signatures, converting legacy global states into parameter-passing variables [541, 543].
