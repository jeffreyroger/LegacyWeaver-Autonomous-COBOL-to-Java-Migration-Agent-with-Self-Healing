      * Phase AA1 fixture (migration-framework-spec.md Section 3.1,
      * hierarchical recursive segment-and-merge) -- a paragraph tree with
      * more paragraphs than a small test budget allows in one block, so
      * weaver/agent/hierarchical_segment.py's recursive splitting is
      * exercised for real, not just against a synthetic list.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BIGPROG.

       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM PARA-A.
           PERFORM PARA-B.
           PERFORM PARA-C.
           PERFORM PARA-D.
           STOP RUN.
       PARA-A.
           PERFORM PARA-E.
           PERFORM PARA-F.
       PARA-B.
           PERFORM PARA-G.
       PARA-C.
           PERFORM PARA-H.
       PARA-D.
           DISPLAY "D".
       PARA-E.
           DISPLAY "E".
       PARA-F.
           DISPLAY "F".
       PARA-G.
           DISPLAY "G".
       PARA-H.
           DISPLAY "H".
