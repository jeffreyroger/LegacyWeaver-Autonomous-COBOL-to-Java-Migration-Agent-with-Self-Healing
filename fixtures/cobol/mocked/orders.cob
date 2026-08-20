      * Phase Z2 fixture (migration-framework-spec.md Section 4.2, Legacy
      * Subsystem Substitutions) -- one paragraph exercising all three
      * modern connector targets: EXEC SQL (-> PostgreSQL), EXEC CICS
      * WRITEQ TS (-> RabbitMQ), EXEC CICS LINK (-> REST). Routed by
      * weaver/agent/connector_map.py; mocked (Phase Z1) for offline
      * verification, real connectors generated (Phase Z2) as migration
      * output.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDERS.

       DATA DIVISION.
       LINKAGE SECTION.
       01  OR-ID                  PIC 9(5)V99.
       01  OR-TOTAL               PIC 9(5)V99.

       PROCEDURE DIVISION USING OR-ID OR-TOTAL.
       MAIN-PARA.
           EXEC SQL
               SELECT PRICE INTO :OR-TOTAL FROM ORDERS
               WHERE ID = :OR-ID
           END-EXEC.
           EXEC CICS
               WRITEQ TS QUEUE('ORDERQ') FROM(OR-TOTAL) LENGTH(8)
           END-EXEC.
           EXEC CICS
               LINK PROGRAM('PRICING') COMMAREA(OR-TOTAL)
           END-EXEC.
           GOBACK.
