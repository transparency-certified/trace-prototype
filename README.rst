=========
TRACE POC
=========


.. image:: https://img.shields.io/pypi/v/trace_poc.svg
        :target: https://pypi.python.org/pypi/trace_poc

.. image:: https://img.shields.io/travis/Xarthisius/trace_poc.svg
        :target: https://travis-ci.com/Xarthisius/trace_poc

.. image:: https://readthedocs.org/projects/trace-poc/badge/?version=latest
        :target: https://trace-poc.readthedocs.io/en/latest/?version=latest
        :alt: Documentation Status




Proposed end-to-end prototype for TRACE project design discussions


* Free software: BSD license
* Documentation: https://trace-poc.readthedocs.io.


Features
--------

* Simple Docker-based job execution service

  * Python REST API
  * repo2docker for image building
  * Executes runs using Docker on the host
  * Configurable claims
  * Uses GPG for signing
  * Creates BagIt-base TRO 

* Python command line tool

  * Submit jobs to server
  * Download TRO
  * Inspect TRO claims 
  * Verify TRO signature via API and using local tools 

How to run?
-----------

.. code-block::
 
   # for client
   virtualenv -p /usr/bin/python3 venv
   . ./venv/bin/activate
   pip install .


   # Generate GPG key
   gpg --full-generate-key
   gpg --list-keys

   # Configure docker-compose.yml
   ...
   - GPG_FINGERPRINT=your_fingerprint
   - GPG_PASSPHRASE=your_passphrase
   ...

   # Create volumes/certs/claims.json. For example:
   {
      "TRACESystem": "TRACE Prototype",
      "TRACEVersion": "0.1",
      "TRACEOrganization": "UIUC",
      "DataAvailablePriorToRuntime": "Yes",
      "DataAvailableAfterRuntime": "Yes",
      "TROIncludesOutputs": "Yes",
      "TROIncludesCode": "Yes",
      "NetworkIsolation": "Yes",
      "PreventsAuthorInteraction": "Yes",
      "InputsFromRepository": "No",
      "TracksIntermediateSteps": "No",
      "IntermediateStepsLevel": "0",
      "RuntimeEvidence": "Yes"
   }

   # Start server. Note, you may need to configure .gpg path
   docker-compose up  # needs v2.x

   # Clone example
   git clone https://github.com/labordynamicsinstitute/example-R-wdata
   cd example-R-wdata

   # Submit the run
   trace-poc submit --entrypoint "run.sh" --container-user rstudio --target-repo-dir "/home/rstudio" .

   ...
   🤘 Finished running
   👛 Baging result
   📜 Signing the bag
   📩 Your magic bag is available as: 659d6ab9-2960-4d1f-8b44-9d41068d4095_run.zip!
   💣 Done!!!

   # Download the TRO
   trace-poc download <run-name>

   Run downloaded as /tmp/<run-name>_run.zip

   # Inspect the TRO
   trace-pos inspect <download-path>

   🔍 Inspecting /tmp/<run-name>_run.zip
	 ⭐ Bagging-Date - 2022-11-06
	 ⭐ Bagging-Time - 15:30:52 UTC
	 ⭐ DataAvailableAfterRuntime - Yes
	 ⭐ DataAvailablePriorToRuntime - Yes
	 ⭐ InputsFromRepository - No
	 ⭐ IntermediateStepsLevel - 0
	 ⭐ NetworkIsolation - Yes
	 ⭐ PreventsAuthorInteraction - Yes
	 ⭐ RuntimeEvidence - Yes
	 ⭐ TRACEOrganization - UIUC
	 ⭐ TRACESystem - TRACE Prototype
	 ⭐ TRACEVersion - 0.1
	 ⭐ TROIncludesCode - Yes
	 ⭐ TROIncludesOutputs - Yes
	 ⭐ TracksIntermediateSteps - No

    # Verify the TRO using API
    trace-poc verify /tmp/a9fc5aa5-b6bf-463a-8477-343f15ab53b9_run.zip
    Signature info:
	creation_date: 2022-11-06
	timestamp: 1667748652
	keyid: F35DE0EBFE748EC4
	username: TRACE POC (TRACE System Proof of Concept) <trace-poc@gmail.com>
	status: signature valid
	fingerprint: 9C71A9331A94D28DA4D56A98F35DE0EBFE748EC4
	expiry: 0
	pubkey_fingerprint: 9C71A9331A94D28DA4D56A98F35DE0EBFE748EC4
	trust_level: 4
	trust_text: TRUST_ULTIMATE
    ✨ Valid and signed bag

    # Verify the TRO locally (assumes key has been imported + trusted)
    $ unzip -qz /tmp/a9fc5aa5-b6bf-463a-8477-343f15ab53b9_run.zip > /tmp/tro.sig
    $ gpg --verify /tmp/tro.sig
    gpg: Signature made Sun Nov  6 15:30:52 2022 UTC
    gpg:                using RSA key 9C71A9331A94D28DA4D56A98F35DE0EBFE748EC4
    gpg: Good signature from "TRACE POC (TRACE System Proof of Concept) <trace-poc@gmail.com>" [ultimate]

Credits
-------

This package was created with Cookiecutter_ and the `audreyr/cookiecutter-pypackage`_ project template.

.. _Cookiecutter: https://github.com/audreyr/cookiecutter
.. _`audreyr/cookiecutter-pypackage`: https://github.com/audreyr/cookiecutter-pypackage
