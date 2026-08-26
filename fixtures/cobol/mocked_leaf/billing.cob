      * Phase Z1 fixture (migration-framework-spec.md Section 2.1, Dynamic
      * Mocking) -- a subprogram whose paragraph makes one EXEC SQL call.
      * weaver/cobol/mock_directives.py + weaver/agent/mock_generator.py
      * rewrite the EXEC SQL block into a deterministic mock before this
      * source is compiled, since GnuCOBOL has no SQL precompiler and this
      * harness has no database to call (CLAUDE.md rule 10).
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BILLING.

       DATA DIVISION.
       LINKAGE SECTION.
       01  BL-ID                  PIC 9(5)V99.
       01  BL-TOTAL               PIC 9(5)V99.

       PROCEDURE DIVISION USING BL-ID BL-TOTAL.
       MAIN-PARA.
           EXEC SQL
               SELECT BALANCE INTO :BL-TOTAL FROM CUSTOMER
               WHERE ID = :BL-ID
           END-EXEC.
           GOBACK.
