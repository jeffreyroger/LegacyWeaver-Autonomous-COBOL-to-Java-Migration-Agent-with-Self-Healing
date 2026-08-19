      *****************************************************************
      * LEAF-A.CBL -- Task 6 multi-program fixture (FR-13.4).
      *
      * True leaf subprogram: no CALL of its own. Doubles a single
      * numeric amount passed via LINKAGE SECTION.
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LEAF-A.

       DATA DIVISION.
       WORKING-STORAGE SECTION.

       LINKAGE SECTION.
       01  LA-INPUT               PIC 9(5)V99.
       01  LA-OUTPUT              PIC 9(5)V99.

       PROCEDURE DIVISION USING LA-INPUT LA-OUTPUT.
       MAIN-PARA.
           COMPUTE LA-OUTPUT = LA-INPUT * 2
           GOBACK.
