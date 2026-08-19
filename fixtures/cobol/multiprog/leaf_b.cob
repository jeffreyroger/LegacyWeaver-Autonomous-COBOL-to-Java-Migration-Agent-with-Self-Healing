      *****************************************************************
      * LEAF-B.CBL -- Task 6 multi-program fixture (FR-13.4).
      *
      * True leaf subprogram: no CALL of its own. Adds a fixed
      * surcharge of 10.00 to a single numeric amount passed via
      * LINKAGE SECTION.
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LEAF-B.

       DATA DIVISION.
       WORKING-STORAGE SECTION.

       LINKAGE SECTION.
       01  LB-INPUT               PIC 9(5)V99.
       01  LB-OUTPUT              PIC 9(5)V99.

       PROCEDURE DIVISION USING LB-INPUT LB-OUTPUT.
       MAIN-PARA.
           COMPUTE LB-OUTPUT = LB-INPUT + 10.00
           GOBACK.
